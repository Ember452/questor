//! Tauri v2 桌面壳装配（Phase 7 T8）。
//!
//! **进程边界铁律（S5 / ADR-0007）**：Rust 壳与 Python harness **只经 HTTP+SSE** 通信，**严禁进程内直调 Python**。
//! 本文件只做壳的接线：拉起 sidecar 子进程、读 bootstrap 拿 loopback 端口、把 webview 指向该端口、
//! 退出时走 `questor-sidecar` 的两级优雅关闭。**生命周期核心逻辑在 `questor-sidecar` crate（已 cargo 验证）**，
//! 这里只是把它接到 tauri 事件循环上。
//!
//! 诚实边界：真窗口渲染 / 全量 `tauri build` 需 WebView2 runtime + tauri CLI + 显示，本机无法验证 → UNVERIFIED。

use questor_sidecar::backend::StdProcess;
use questor_sidecar::{resolve_sidecar, two_phase_shutdown, wait_ready, Fence, Shutdown};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::Manager;

/// 优雅关闭总宽限（对齐参考仓 sidecar.rs 的 SHUTDOWN_EXIT_GRACE）：先发请求、轮询、超时强杀。
const GRACE: Duration = Duration::from_secs(35);
/// 轮询子进程退出的间隔。
const POLL: Duration = Duration::from_millis(200);
/// 等 sidecar 写 bootstrap 的上限（serve 起 uvicorn 需要点时间）。
const BOOTSTRAP_WAIT: Duration = Duration::from_secs(40);

/// sidecar bootstrap 契约（与 `surfaces/serve.py::write_bootstrap` 字段一致）。
#[derive(serde::Deserialize)]
struct Bootstrap {
    #[allow(dead_code)]
    host: String,
    port: u16,
    generation: u64,
    token: String,
}

/// tauri 管理状态：持有当前 sidecar 子进程句柄 + 端口/token，供退出时优雅关闭。
struct SidecarCell(Mutex<Option<(StdProcess, u64, u16, String)>>);

fn bootstrap_path() -> PathBuf {
    std::env::var_os("QUESTOR_SIDECAR_BOOTSTRAP")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(".questor").join("sidecar-bootstrap.json"))
}

/// 启动（或重启）sidecar：bump generation → 设 env → 按 resolve 出的 (program,args) spawn → 读 bootstrap → 就绪探测。
/// program/args 由 `resolve_sidecar`（env→发布资源→开发态）决定；发布态不写死 `python`（§6-1）。
fn start_sidecar(
    fence: &Fence,
    program: &str,
    args: &[String],
) -> Result<(StdProcess, u16, u64, String), String> {
    let generation = fence.bump();
    let bp = bootstrap_path();
    let _ = std::fs::remove_file(&bp);
    // 代次随 env 注入子进程（serve 侧读之写进 bootstrap），实现"陈旧连接栅栏"的比对基。
    std::env::set_var("QUESTOR_SIDECAR_BOOTSTRAP", &bp);
    std::env::set_var("QUESTOR_SIDECAR_GENERATION", generation.to_string());

    let arg_refs: Vec<&str> = args.iter().map(String::as_str).collect();
    let proc = StdProcess::spawn(program, &arg_refs).map_err(|e| format!("spawn sidecar: {e}"))?;

    let deadline = Instant::now() + BOOTSTRAP_WAIT;
    let boot = loop {
        if let Ok(raw) = std::fs::read_to_string(&bp) {
            if let Ok(b) = serde_json::from_str::<Bootstrap>(&raw) {
                break b;
            }
        }
        if Instant::now() >= deadline {
            return Err("sidecar never wrote bootstrap".into());
        }
        std::thread::sleep(Duration::from_millis(100));
    };
    if !wait_ready(boot.port, Duration::from_secs(20)) {
        return Err(format!("sidecar port {} never became ready", boot.port));
    }
    Ok((proc, boot.port, boot.generation, boot.token))
}

/// 向 sidecar 发一个真优雅关闭 RPC（POST /shutdown，带 token）。经裸 TcpStream 手写 HTTP（壳侧零依赖）；
/// 任何失败都忽略（则两级关闭落到 grace 超时后的 force_kill 兜底）。
fn send_shutdown(port: u16, token: &str) {
    use std::io::{Read, Write};
    use std::net::TcpStream;
    let addr = format!("127.0.0.1:{port}");
    if let Ok(mut stream) = TcpStream::connect(&addr) {
        let req = format!(
            "POST /shutdown HTTP/1.1\r\nHost: {addr}\r\nx-questor-token: {token}\r\ncontent-length: 0\r\nconnection: close\r\n\r\n"
        );
        let _ = stream.write_all(req.as_bytes());
        let _ = stream.flush();
        let mut buf = [0u8; 128];
        let _ = stream.read(&mut buf); // 尽力读完响应，不阻塞关闭
    }
}

/// 两级优雅关闭：① 向 sidecar POST /shutdown → ② 轮询子进程退出 → ③ 超时 force_kill。
/// 正常路径下 sidecar 收到 /shutdown 后 uvicorn 应声优雅退→ poll 拿到退出码 → Exited（非恒 35s 硬杀）。
fn shutdown_sidecar(cell: &SidecarCell) {
    let taken = cell.0.lock().map(|mut g| g.take()).unwrap_or(None);
    if let Some((mut proc, _gen, port, token)) = taken {
        let out = two_phase_shutdown(|| send_shutdown(port, &token), &mut proc, GRACE, POLL);
        match out {
            Shutdown::Exited => log("sidecar exited gracefully"),
            Shutdown::ForceKilled => log("sidecar force-killed after grace"),
        }
    }
}

fn log(msg: &str) {
    eprintln!("[questor-desktop] {msg}");
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let fence = Fence::new();
    tauri::Builder::default()
        .setup(move |app| {
            // 解析 sidecar 可执行体：env 覆盖 → 发布态资源目录二进制 → 开发态 python（§6-1：发布态绝不回退系统 Python）。
            let packaged = app.path().resource_dir().ok().map(|r| {
                r.join("sidecar")
                    .join("questor-sidecar")
                    .join(if cfg!(windows) {
                        "questor-sidecar.exe"
                    } else {
                        "questor-sidecar"
                    })
            });
            let (program, args) = resolve_sidecar(
                std::env::var("QUESTOR_SIDECAR_BIN").ok(),
                packaged,
                "python",
            );
            let (proc, port, _gen, token) = start_sidecar(&fence, &program, &args)
                .map_err(|e| format!("sidecar start failed: {e}"))?;
            // webview 指向 loopback sidecar，并把会话 token 经查询注入（前端据此带 header）。
            // 先构 URL（借用 token），再 manage（移动 token）——避免借用/移动顺序错。
            let url: tauri::Url = format!("http://127.0.0.1:{port}/?token={token}")
                .parse()
                .map_err(|e| format!("bad sidecar url: {e}"))?;
            app.manage(SidecarCell(Mutex::new(Some((proc, _gen, port, token)))));
            let win =
                tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::External(url))
                    .title("Questor")
                    .inner_size(1100.0, 760.0)
                    .build()
                    .map_err(|e| format!("window build failed: {e}"))?;
            win.set_focus().ok();
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building questor desktop shell")
        .run(|app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(cell) = app_handle.try_state::<SidecarCell>() {
                    shutdown_sidecar(&cell);
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    /// bootstrap 解析必须与 Python `write_bootstrap` 的字段契约一致（跨语言 wire 面，C15 精神）。
    #[test]
    fn bootstrap_json_parses() {
        let raw =
            r#"{"host":"127.0.0.1","port":54321,"generation":7,"pid":4242,"token":"tok-abc"}"#;
        let b: Bootstrap = serde_json::from_str(raw).unwrap();
        assert_eq!(b.port, 54321);
        assert_eq!(b.generation, 7);
        assert_eq!(b.token, "tok-abc");
    }

    #[test]
    fn shutdown_of_absent_sidecar_is_noop() {
        let cell = SidecarCell(Mutex::new(None));
        shutdown_sidecar(&cell); // 不应 panic
    }

    #[test]
    fn send_shutdown_without_listener_is_ignored() {
        // 端口 1 无监听 → TcpStream::connect 失败应静默忽略（优雅关闭降级到 force_kill 兜底），绝不 panic。
        send_shutdown(1, "tok");
    }
}
