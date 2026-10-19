//! Tauri v2 桌面壳装配（Phase 7 T8）。
//!
//! **进程边界铁律（S5 / ADR-0007）**：Rust 壳与 Python harness **只经 HTTP+SSE** 通信，**严禁进程内直调 Python**。
//! 本文件只做壳的接线：拉起 sidecar 子进程、读 bootstrap 拿 loopback 端口、把 webview 指向该端口、
//! 退出时走 `questor-sidecar` 的两级优雅关闭。**生命周期核心逻辑在 `questor-sidecar` crate（已 cargo 验证）**，
//! 这里只是把它接到 tauri 事件循环上。
//!
//! 诚实边界：真窗口渲染 / 全量 `tauri build` 需 WebView2 runtime + tauri CLI + 显示，本机无法验证 → UNVERIFIED。

use questor_sidecar::backend::StdProcess;
use questor_sidecar::{resolve_sidecar, two_phase_shutdown, wait_ready, Fence, Process, Shutdown};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager};

/// 优雅关闭总宽限：先发请求、轮询、超时强杀。
const GRACE: Duration = Duration::from_secs(35);
/// 轮询子进程退出的间隔。
const POLL: Duration = Duration::from_millis(200);
/// 等 sidecar 写 bootstrap 的上限（serve 起 uvicorn 需要点时间）。
const BOOTSTRAP_WAIT: Duration = Duration::from_secs(40);
/// §6-5 崩溃监控线程轮询子进程的间隔。
const MONITOR_TICK: Duration = Duration::from_millis(500);
/// §6-6：连续崩溃重启上限，超限停监控（避免崩溃循环烧 CPU）。
const MAX_RESTARTS: usize = 5;

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

/// §6-5：主动关窗标志——监控线程据此区分崩溃 vs 优雅停机，避免误报 Crashed。
struct ShuttingDown(AtomicBool);

/// §6-5：壳→UI 的进程级 sidecar_status wire 载荷（与 protocol/sidecar_status.schema.json 同形）。
#[derive(serde::Serialize, Clone)]
struct StatusPayload<'a> {
    state: &'a str,
    generation: u64,
    detail: Option<&'a str>,
}

/// 构造 status 载荷（纯函数，单测锁字段名 = Rust↔contracts 序列化 lockstep）。
fn status_payload<'a>(
    state: &'a str,
    generation: u64,
    detail: Option<&'a str>,
) -> StatusPayload<'a> {
    StatusPayload {
        state,
        generation,
        detail,
    }
}

/// §6-5/6-6 监控重启循环：轮询子进程；非主动停机下若退出 → emit crashed，再 `start_sidecar` 重挂
/// （`fence.bump` 于其中发生，陈旧 SSE/回执自然作废）→ 换新 bootstrap 的 port/token → 重导航 webview → emit ready。
/// 连撞上限 `MAX_RESTARTS` 则 emit stopped 停循。**诚实边界**：respawn + webview 重导航集成行为需真桌面实测 → headless UNVERIFIED；
/// 壳非事件 broker（webview 直连 sidecar），无壳侧 pending 可 fail_all；在途 run 的 after_seq 重挂属 §6-8。
fn monitor_sidecar_loop(
    handle: tauri::AppHandle,
    fence: Fence,
    program: String,
    args: Vec<String>,
) {
    let mut restarts = 0usize;
    loop {
        std::thread::sleep(MONITOR_TICK);
        let shutting_down = handle
            .try_state::<ShuttingDown>()
            .map(|f| f.0.load(Ordering::SeqCst))
            .unwrap_or(true); // 状态缺失（异常拆毁）→ 保守停监控。
        if shutting_down {
            return; // 主动关窗：非崩溃。
        }
        // 短暂持锁轮询当前子进程退出（不跨 sleep 持锁，避免阻住优雅关闭路径）。
        let exited = {
            let Some(cell) = handle.try_state::<SidecarCell>() else {
                return;
            };
            let mut guard = match cell.0.lock() {
                Ok(g) => g,
                Err(_) => return,
            };
            match guard.as_mut() {
                Some((proc, gen, _port, _tok)) => proc.poll().map(|code| (*gen, code)),
                None => return, // 已被 shutdown take → 主动停机
            }
        };
        let Some((gen, code)) = exited else { continue };
        // 崩溃出声（错误类必报，C6/§6-5）。
        let detail = format!("exit {code}");
        let _ = handle.emit(
            "sidecar_status",
            status_payload("crashed", gen, Some(&detail)),
        );
        if restarts >= MAX_RESTARTS {
            let _ = handle.emit(
                "sidecar_status",
                status_payload("stopped", gen, Some("restart limit hit")),
            );
            log("sidecar restart limit hit; monitor stops");
            return;
        }
        restarts += 1;
        // respawn：start_sidecar 内 bump generation + 写新 bootstrap + wait_ready。
        match start_sidecar(&fence, &program, &args) {
            Ok((proc, port, new_gen, token)) => {
                let url: tauri::Url =
                    match format!("http://127.0.0.1:{port}/?token={token}").parse() {
                        Ok(u) => u,
                        Err(_) => {
                            let _ = handle.emit(
                                "sidecar_status",
                                status_payload("stopped", new_gen, Some("bad url")),
                            );
                            return;
                        }
                    };
                // 替换托管 cell（旧死 proc 在此 drop → 回收），供优雅关闭接手新进程。
                if let Some(cell) = handle.try_state::<SidecarCell>() {
                    if let Ok(mut g) = cell.0.lock() {
                        *g = Some((proc, new_gen, port, token));
                    }
                }
                if let Some(win) = handle.get_webview_window("main") {
                    let _ = win.navigate(url); // 重导航到新端口/新 token。
                }
                let _ = handle.emit("sidecar_status", status_payload("ready", new_gen, None));
                log(&format!("sidecar restarted gen={new_gen} port={port}"));
            }
            Err(e) => {
                let _ = handle.emit("sidecar_status", status_payload("stopped", gen, Some(&e)));
                log("sidecar restart failed; monitor stops");
                return;
            }
        }
    }
}

fn bootstrap_path() -> PathBuf {
    std::env::var_os("QUESTOR_SIDECAR_BOOTSTRAP")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(".questor").join("sidecar-bootstrap.json"))
}

/// dev 态前端静态产物默认路径：`src-tauri` 的兄弟目录 `web/dist`（纯路径运算，不触碰文件系统，可单测）。
fn dev_web_dist_default(manifest_dir: &std::path::Path) -> PathBuf {
    manifest_dir
        .parent()
        .map(|p| p.join("web").join("dist"))
        .unwrap_or_else(|| manifest_dir.join("web").join("dist"))
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
            // dev 态（debug 构建）且操作者未显式指定时，注入前端产物默认路径，免去每窗口手设 env；
            // 发布态（release）绝不注入——前端由 PyInstaller 资源目录伺服。已设则尊重不覆盖。
            if cfg!(debug_assertions) && std::env::var_os("QUESTOR_WEB_DIST").is_none() {
                let dist = dev_web_dist_default(std::path::Path::new(env!("CARGO_MANIFEST_DIR")));
                std::env::set_var("QUESTOR_WEB_DIST", &dist);
            }
            let (proc, port, gen, token) = start_sidecar(&fence, &program, &args)
                .map_err(|e| format!("sidecar start failed: {e}"))?;
            // webview 指向 loopback sidecar，并把会话 token 经查询注入（前端据此带 header）。
            // 先构 URL（借用 token），再 manage（移动 token）——避免借用/移动顺序错。
            let url: tauri::Url = format!("http://127.0.0.1:{port}/?token={token}")
                .parse()
                .map_err(|e| format!("bad sidecar url: {e}"))?;
            app.manage(SidecarCell(Mutex::new(Some((proc, gen, port, token)))));
            app.manage(ShuttingDown(AtomicBool::new(false)));
            let win =
                tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::External(url))
                    .title("Questor")
                    .inner_size(1100.0, 760.0)
                    .build()
                    .map_err(|e| format!("window build failed: {e}"))?;
            win.set_focus().ok();
            // §6-5/6-6：sidecar 就绪 → emit ready；起监控重启循环（崩溃→emit→respawn→重导航→emit ready）。
            let handle = app.handle().clone();
            let _ = handle.emit("sidecar_status", status_payload("ready", gen, None));
            std::thread::spawn(move || monitor_sidecar_loop(handle, fence, program, args));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building questor desktop shell")
        .run(|app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                // 先置停机标志，让监控线程把这当作主动关闭、不误报 Crashed。
                if let Some(flag) = app_handle.try_state::<ShuttingDown>() {
                    flag.0.store(true, Ordering::SeqCst);
                }
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

    /// §6-5：壳发的 sidecar_status 载荷必须与 wire 契约同形（字段名 state/generation/detail）。
    /// 这是 Rust↔contracts 的序列化 lockstep：改名/增删字段此测即红（与 Python 字段级漂移门同经同纬）。
    #[test]
    fn sidecar_status_payload_matches_wire_contract() {
        let v = serde_json::to_value(status_payload("crashed", 3, Some("exit 1"))).unwrap();
        assert_eq!(v["state"], serde_json::json!("crashed"));
        assert_eq!(v["generation"], serde_json::json!(3));
        assert_eq!(v["detail"], serde_json::json!("exit 1"));
        let mut keys: Vec<String> = v.as_object().unwrap().keys().cloned().collect();
        keys.sort();
        assert_eq!(keys, vec!["detail", "generation", "state"]);
        // detail 省略时序列化为 null（与 schema 的 ["string","null"] 一致）。
        let v2 = serde_json::to_value(status_payload("ready", 1, None)).unwrap();
        assert!(v2["detail"].is_null());
    }

    /// dev 默认前端产物路径 = src-tauri 的兄弟目录 `web/dist`（纯路径运算，不触碰文件系统）。
    #[test]
    fn dev_web_dist_default_points_to_sibling_web_dist() {
        let got =
            super::dev_web_dist_default(std::path::Path::new("/abs/project/desktop/src-tauri"));
        let want = std::path::Path::new("/abs/project/desktop/web/dist");
        assert_eq!(got, want);
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
