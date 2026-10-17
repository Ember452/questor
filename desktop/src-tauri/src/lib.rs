//! Tauri v2 桌面壳装配（Phase 7 T8）。
//!
//! **进程边界铁律（S5 / ADR-0007）**：Rust 壳与 Python harness **只经 HTTP+SSE** 通信，**严禁进程内直调 Python**。
//! 本文件只做壳的接线：拉起 sidecar 子进程、读 bootstrap 拿 loopback 端口、把 webview 指向该端口、
//! 退出时走 `questor-sidecar` 的两级优雅关闭。**生命周期核心逻辑在 `questor-sidecar` crate（已 cargo 验证）**，
//! 这里只是把它接到 tauri 事件循环上。
//!
//! 诚实边界：真窗口渲染 / 全量 `tauri build` 需 WebView2 runtime + tauri CLI + 显示，本机无法验证 → UNVERIFIED。

use questor_sidecar::backend::StdProcess;
use questor_sidecar::{two_phase_shutdown, wait_ready, Fence, Shutdown};
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
}

/// tauri 管理状态：持有当前 sidecar 子进程句柄，供退出时优雅关闭。
struct SidecarCell(Mutex<Option<(StdProcess, u64)>>);

fn bootstrap_path() -> PathBuf {
    std::env::var_os("QUESTOR_SIDECAR_BOOTSTRAP")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(".questor").join("sidecar-bootstrap.json"))
}

/// 启动（或重启）sidecar：bump generation → 设 env → spawn `python -m questor --serve` → 读 bootstrap → 就绪探测。
fn start_sidecar(fence: &Fence) -> Result<(StdProcess, u16, u64), String> {
    let generation = fence.bump();
    let bp = bootstrap_path();
    let _ = std::fs::remove_file(&bp);
    // 代次随 env 注入子进程（serve 侧读之写进 bootstrap），实现"陈旧连接栅栏"的比对基。
    std::env::set_var("QUESTOR_SIDECAR_BOOTSTRAP", &bp);
    std::env::set_var("QUESTOR_SIDECAR_GENERATION", generation.to_string());

    let proc = StdProcess::spawn("python", &["-m", "questor", "--serve"]).map_err(|e| format!("spawn sidecar: {e}"))?;

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
    Ok((proc, boot.port, boot.generation))
}

/// 两级优雅关闭：向 sidecar 发关闭意图 → 轮询 → 超时 force_kill；无论哪级都让 fail_all 语义在 sidecar 侧
/// 由其自身 teardown 收尾（Rust 侧只需保证进程被回收，不留孤儿）。
fn shutdown_sidecar(cell: &SidecarCell) {
    let taken = cell.0.lock().map(|mut g| g.take()).unwrap_or(None);
    if let Some((mut proc, _gen)) = taken {
        let out = two_phase_shutdown(
            || {
                // 生产应经 HTTP 向 sidecar 发优雅关闭；本 Phase sidecar 尚无 /shutdown RPC 端点，
                // 故请求为 no-op，落到 grace 超时后的 force_kill 兜底（诚实：非理想优雅路径）。
            },
            &mut proc,
            GRACE,
            POLL,
        );
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
            let (proc, port, _gen) = start_sidecar(&fence).map_err(|e| format!("sidecar start failed: {e}"))?;
            app.manage(SidecarCell(Mutex::new(Some((proc, _gen)))));
            // webview 指向 loopback sidecar —— 桌面只是薄壳，全部业务在 Python（S5/S6）。
            let url: tauri::Url = format!("http://127.0.0.1:{port}")
                .parse()
                .map_err(|e| format!("bad sidecar url: {e}"))?;
            let win = tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::External(url))
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
        let raw = r#"{"host":"127.0.0.1","port":54321,"generation":7,"pid":4242}"#;
        let b: Bootstrap = serde_json::from_str(raw).unwrap();
        assert_eq!(b.port, 54321);
        assert_eq!(b.generation, 7);
    }

    #[test]
    fn shutdown_of_absent_sidecar_is_noop() {
        let cell = SidecarCell(Mutex::new(None));
        shutdown_sidecar(&cell); // 不应 panic
    }
}
