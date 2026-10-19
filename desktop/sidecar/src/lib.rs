//! Python sidecar 生命周期监管**核心状态机**（Phase 7 T8 / ADR-0032；HARD S5/C10/C19）。
//!
//! 这里是**纯逻辑、零外部依赖**，好让 `cargo test` 快速、确定性地验证最难的部分：
//! - **generation 栅栏**：每次重启自增，携带旧 generation 的连接/回执一律判为陈旧丢弃
//!   （防“重启后陈旧连接写新 run”）。
//! - **两级优雅关闭**：先 `request`（sidecar 的 shutdown 调用）→ 轮询子进程 `poll` 到 `grace` 上限
//!   → 超时 `force_kill` 兜底。无论走哪级，都在返回前给出确定终态。
//! - **`fail_all`**：崩溃/关闭时把在途 pending 全标记为 Failed，使 pending 不撕裂状态（C10/C19 的
//!   "先推部分事件后不得让消费方误解"在生命周期侧的对应物）。
//! - **loopback 就绪探测**：轮询 `127.0.0.1:<port>` 可连即 ready（ADR-0007）。
//!
//! OS 进程/Windows Job Object 真后端在 `backend.rs`（生产用）；本模块只依赖 `trait` 抽象，便于 mock 测。

use std::net::{SocketAddr, TcpStream};
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::{Duration, Instant};

pub mod backend;

/// sidecar 代次。每次（重）起自增；`0` 表示从未启动。
pub type Generation = u64;

/// generation 栅栏：重启计数 + 陈旧判定。Rust 壳与 sidecar bootstrap 共用它的语义。
#[derive(Default)]
pub struct Fence {
    current: AtomicU64,
}

impl Fence {
    pub fn new() -> Self {
        Self::default()
    }

    /// 当前 generation。
    pub fn current(&self) -> Generation {
        self.current.load(Ordering::SeqCst)
    }

    /// 记一次（重）启动：自增并返回新 generation。
    pub fn bump(&self) -> Generation {
        self.current.fetch_add(1, Ordering::SeqCst) + 1
    }

    /// 给定 generation 是否仍是当前代（否则为陈旧连接/回执，应丢弃）。
    pub fn is_current(&self, gen: Generation) -> bool {
        self.current.load(Ordering::SeqCst) == gen
    }
}

/// 抽象子进程句柄：生产实现见 `backend.rs`（`std::process::Child` + Job Object）；测试用假实现。
pub trait Process {
    /// 非阻塞轮询退出：`Some(code)` 已退出；`None` 仍在跑。
    fn poll(&mut self) -> Option<i32>;
    /// 强制杀（含进程树；Windows 走 Job Object）。
    fn force_kill(&mut self);
}

/// 两级优雅关闭的终态。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Shutdown {
    /// 收到 shutdown 请求后在 grace 内自行退出。
    Exited,
    /// grace 到点仍未退出，已 `force_kill` 兜底。
    ForceKilled,
}

/// 两级优雅关闭：① `request`（向 sidecar 发 shutdown 调用）→ ② 轮询到 `grace` 上限 → ③ 超时 `force_kill`。
///
/// 失败语义：本函数不抛错；无论哪一级都在返回时给出确定终态，调用方据 `Shutdown` 决定后续
/// （通常紧接 `fail_all` 使在途 pending 全 fail）。
pub fn two_phase_shutdown<P: Process, R: FnMut()>(
    mut request: R,
    proc: &mut P,
    grace: Duration,
    poll: Duration,
) -> Shutdown {
    request(); // ① 优雅关闭请求（HTTP/RPC），不是硬杀
    let start = Instant::now();
    loop {
        if proc.poll().is_some() {
            return Shutdown::Exited;
        }
        if start.elapsed() >= grace {
            proc.force_kill(); // ③ 兜底强杀
            return Shutdown::ForceKilled;
        }
        thread::sleep(poll);
    }
}

/// 在途请求状态。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RequestState {
    Pending,
    Failed,
    Closed,
}

/// 一条在途请求（对应一个 sidecar 侧 pending tool_use / SSE 会话）。
#[derive(Debug, Clone)]
pub struct PendingRequest {
    pub id: String,
    pub generation: Generation,
    pub state: RequestState,
}

/// 崩溃/关闭时把所有 `Pending` 置 `Failed` 并返回处理条数（pending 全 fail，不撕裂状态，C10/C19）。
///
/// 只动 `Pending`：`Closed`（已完成）不被误改；`Failed` 幂等（不重复计数）。
pub fn fail_all(reqs: &mut [PendingRequest], generation: Generation) -> usize {
    let mut n = 0;
    for r in reqs.iter_mut() {
        // 只失效**当前代**的 pending：旧代请求由栅栏另行处理，不在此翻案。
        if r.generation == generation && r.state == RequestState::Pending {
            r.state = RequestState::Failed;
            n += 1;
        }
    }
    n
}

/// 轮询 `127.0.0.1:<port>` 直到可连（就绪）或超时。ADR-0007/ADR-0032 的就绪探测（替代 stdin 握手）。
///
/// 只连 loopback，绝不接受外部 host（本地 IPC，无网络出口，呼应 C12）。
pub fn wait_ready(port: u16, timeout: Duration) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let deadline = Instant::now() + timeout;
    loop {
        if TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
            return true;
        }
        if Instant::now() >= deadline {
            return false;
        }
        thread::sleep(Duration::from_millis(50));
    }
}

/// 一次崩溃检测/重启决策（DoD③）：若子进程已退出（poll Some）且非主动关闭，则 `fail_all` 当前代 pending
/// （在途请求不摊塌状态）+ `bump`  generation（陈旧连接从此作废），返回 Some(新代)=应重启；否则 None。
///
/// 这是壳的重启监控循环每一拍调用的**纯决策**（真 spawn/restart 由调用方注入），以便用假 `Process` 确定性单测。
/// 重启次数上限等策略由调用方控制（`max_restarts` 达限则返回 None 停止重启）。
pub fn on_crash_detect<P: Process>(
    fence: &Fence,
    generation: Generation,
    proc: &mut P,
    pending: &mut [PendingRequest],
    shutting_down: bool,
) -> Option<Generation> {
    if shutting_down {
        return None; // 主动关闭路径：不当崩溃处理，不重启。
    }
    if proc.poll().is_some() {
        fail_all(pending, generation); // 崩溃时在途 pending 全 fail（C10/C19）
        return Some(fence.bump()); // 代次自增：旧 SSE/回执栅栏丢弃
    }
    None
}

/// sidecar 启动命令解析（§6-1 专项5：“发布态绝不回退系统 Python”）。
///
/// 优先级：**env 覆盖** `QUESTOR_SIDECAR_BIN`（指向冻结产物）→ **发布态资源目录内的二进制**（若存在）
/// → **开发态** `python -m questor --serve`（仅当 env 与打包二进制都不在）。返回 (program, args)。
/// 冻结产物入口自带 `--serve`，故 args 为空；开发态需 `-m questor --serve`。
pub fn resolve_sidecar(
    env_bin: Option<String>,
    packaged: Option<std::path::PathBuf>,
    dev_python: &str,
) -> (String, Vec<String>) {
    if let Some(bin) = env_bin.filter(|s| !s.trim().is_empty()) {
        return (bin, vec![]);
    }
    if let Some(path) = packaged.filter(|p| p.exists()) {
        return (path.to_string_lossy().into_owned(), vec![]);
    }
    (
        dev_python.to_string(),
        vec!["-m".into(), "questor".into(), "--serve".into()],
    )
}

#[cfg(test)]
mod resolve_tests {
    use super::resolve_sidecar;

    #[test]
    fn env_override_wins_and_takes_no_args() {
        let (prog, args) = resolve_sidecar(Some("/opt/questor-sidecar".into()), None, "python");
        assert_eq!(prog, "/opt/questor-sidecar");
        assert!(args.is_empty());
    }

    #[test]
    fn packaged_binary_used_when_present() {
        let dir = std::env::temp_dir();
        let exe = dir.join(format!("qs-packaged-{}", std::process::id()));
        std::fs::write(&exe, b"x").unwrap();
        let (prog, args) = resolve_sidecar(None, Some(exe.clone()), "python");
        assert_eq!(prog, exe.to_string_lossy());
        assert!(args.is_empty());
        let _ = std::fs::remove_file(&exe);
    }

    #[test]
    fn falls_back_to_dev_python_only_when_nothing_else() {
        // env 空 + 打包二进制不存在 → 开发态 python -m questor --serve。
        let missing = std::path::PathBuf::from("/nonexistent/questor-sidecar");
        let (prog, args) = resolve_sidecar(Some("".into()), Some(missing), "python");
        assert_eq!(prog, "python");
        assert_eq!(args, vec!["-m", "questor", "--serve"]);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fence_bumps_and_rejects_stale() {
        let fence = Fence::new();
        assert_eq!(fence.current(), 0);
        let g1 = fence.bump();
        assert_eq!(g1, 1);
        assert!(fence.is_current(1));
        assert!(!fence.is_current(0), "重启前的 generation 0 应判为陈旧");
        let g2 = fence.bump();
        assert_eq!(g2, 2);
        assert!(!fence.is_current(1), "上一代连接重启后应被栅栏丢弃");
    }

    struct FakeProc {
        exit_after_polls: usize,
        polls: usize,
        killed: bool,
    }
    impl Process for FakeProc {
        fn poll(&mut self) -> Option<i32> {
            self.polls += 1;
            if self.polls >= self.exit_after_polls {
                Some(0)
            } else {
                None
            }
        }
        fn force_kill(&mut self) {
            self.killed = true;
        }
    }

    #[test]
    fn two_phase_exits_gracefully() {
        // 子进程在收到请求后很快退出 → Exited，且**不应**走到 force_kill。
        let mut proc = FakeProc {
            exit_after_polls: 2,
            polls: 0,
            killed: false,
        };
        let mut requested = false;
        let out = two_phase_shutdown(
            || requested = true,
            &mut proc,
            Duration::from_millis(500),
            Duration::from_millis(5),
        );
        assert_eq!(out, Shutdown::Exited);
        assert!(requested, "必须先发优雅关闭请求");
        assert!(!proc.killed, "优雅退出路径不应强杀");
    }

    #[test]
    fn two_phase_force_kills_on_grace_timeout() {
        // 子进程永不退出 → 到 grace 触发 force_kill → ForceKilled。
        let mut proc = FakeProc {
            exit_after_polls: usize::MAX,
            polls: 0,
            killed: false,
        };
        let out = two_phase_shutdown(
            || {},
            &mut proc,
            Duration::from_millis(50),
            Duration::from_millis(5),
        );
        assert_eq!(out, Shutdown::ForceKilled);
        assert!(proc.killed, "超 grace 必须强杀兜底");
    }

    struct Running; // 永不退出
    impl Process for Running {
        fn poll(&mut self) -> Option<i32> {
            None
        }
        fn force_kill(&mut self) {}
    }

    struct Crashed; // 立刻报已退出
    impl Process for Crashed {
        fn poll(&mut self) -> Option<i32> {
            Some(1)
        }
        fn force_kill(&mut self) {}
    }

    #[test]
    fn crash_detect_bumps_and_fails_only_when_exited_not_shutting_down() {
        let fence = Fence::new();
        let gen = fence.bump(); // gen=1
        let mut pending = vec![PendingRequest {
            id: "p".into(),
            generation: gen,
            state: RequestState::Pending,
        }];
        // 运行中：不触发。
        assert!(
            on_crash_detect(&fence, gen, &mut Running, pending.as_mut_slice(), false).is_none()
        );
        // 主动关闭：不触发、不 fail。
        assert!(on_crash_detect(&fence, gen, &mut Crashed, pending.as_mut_slice(), true).is_none());
        assert_eq!(pending[0].state, RequestState::Pending);
        // 崩溃（非主动）：fail_all + bump → 返回新代 2。
        let next = on_crash_detect(&fence, gen, &mut Crashed, pending.as_mut_slice(), false);
        assert_eq!(next, Some(2));
        assert_eq!(pending[0].state, RequestState::Failed);
        assert_eq!(fence.current(), 2);
    }

    #[test]
    fn fail_all_marks_only_current_generation_pending() {
        let mut reqs = vec![
            PendingRequest {
                id: "a".into(),
                generation: 1,
                state: RequestState::Pending,
            },
            PendingRequest {
                id: "b".into(),
                generation: 1,
                state: RequestState::Closed,
            },
            PendingRequest {
                id: "c".into(),
                generation: 2,
                state: RequestState::Pending,
            },
        ];
        let n = fail_all(&mut reqs, 1);
        assert_eq!(n, 1, "只失效当前代 pending（b 已 Closed 不动、c 是别的代）");
        assert_eq!(reqs[0].state, RequestState::Failed);
        assert_eq!(reqs[1].state, RequestState::Closed);
        assert_eq!(reqs[2].state, RequestState::Pending);
    }

    #[test]
    fn wait_ready_true_against_listener() {
        // 真 loopback：起一个 listener → wait_ready 应在超时前返回 true。
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        thread::spawn(move || {
            for stream in listener.incoming() {
                drop(stream.ok());
            }
        });
        assert!(wait_ready(port, Duration::from_millis(2000)));
    }

    #[test]
    fn wait_ready_false_when_nothing_listens() {
        // 占一个口再释放，得到一个大概率无人监听的口 → wait_ready 应超时返回 false。
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        drop(listener);
        assert!(!wait_ready(port, Duration::from_millis(200)));
    }
}
