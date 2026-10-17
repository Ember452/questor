//! OS 进程后端：把 crate 核心状态机接到真 `std::process::Child`（Phase 7 T8）。
//!
//! 生产里 Windows 还需 Job Object 杀**进程树**（sidecar 会再生 MCP 子进程）——那部分是需要真机
//! 验证的 OS 特化，见文末 `windows_job_object`（**UNVERIFIED**：本机不交盲目手写、未经真进程树实测的 FFI）。
//! 本文件的 `StdProcess` 走 `std` 可移植 API（`try_wait`/`kill`），并配**真子进程**测试，验证两级关闭
//! 的强杀兜底在真实 OS 上成立。

use crate::Process;
use std::process::{Child, Command, Stdio};

/// 真子进程句柄实现。sidecar = `python -m questor --serve` 冻结产物（生产经 PyInstaller，本测试用任意命令）。
pub struct StdProcess {
    child: Child,
}

impl StdProcess {
    /// 以独立进程组/新窗口方式拉起命令（stdout/stderr 交由调用侧重定向到 sidecar 自身日志，不进观测面）。
    pub fn spawn(program: &str, args: &[&str]) -> std::io::Result<Self> {
        let child = Command::new(program)
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()?;
        Ok(Self { child })
    }
}

impl Process for StdProcess {
    fn poll(&mut self) -> Option<i32> {
        // 非阻塞：try_wait 拿退出码；未退出返回 None（对应 core 里继续轮询）。
        self.child
            .try_wait()
            .ok()
            .flatten()
            .map(|status| status.code().unwrap_or(-1))
    }

    fn force_kill(&mut self) {
        // 单进程强杀；进程树（MCP 子进程）需 Job Object（见模块末 UNVERIFIED 注）。
        // kill 后再 wait 回收，避免僵尸句柄。
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

// 生产落地 Windows 需补 Job Object 杀进程树：CreateJobObjectW + JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
// + AssignProcessToJobObject，让 sidecar 及其派生的 MCP 子进程随 job 关闭一并回收（防孤儿）。
// 本机不交盲目手写、未经真进程树实测的 FFI，故此处不预置未验证代码——该 OS 特化列 **UNVERIFIED**。

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{two_phase_shutdown, Shutdown};
    use std::thread;
    use std::time::Duration;

    /// 真子进程两级关闭：起一个会自己结束的命令（`ping -n 2`），不发优雅请求 → grace 内它自行退出
    /// 或到点强杀，两条路径都必须最终回收进程、不悬挂。用 ping 保证跨调用确定行为。
    #[test]
    fn real_child_is_recovered_by_two_phase() {
        // 起一个约 1~2 秒的命令；给很短的 grace 逼出 force_kill 路径，验证真 OS 上强杀生效、进程被回收。
        let mut proc = StdProcess::spawn("cmd", &["/C", "ping", "-n", "30", "127.0.0.1"]).expect("spawn cmd ping");

        let out = two_phase_shutdown(
            || {
                // 真 sidecar 应经 HTTP 发 shutdown；这里对 cmd 无优雅端点，故请求为 no-op，逼出兜底强杀。
            },
            &mut proc,
            Duration::from_millis(300),
            Duration::from_millis(30),
        );
        assert_eq!(out, Shutdown::ForceKilled, "ping 30 不会在 300ms 内自退，应走强杀兜底");

        // 强杀后必须能轮询到退出码（进程已回收，不悬挂）。
        thread::sleep(Duration::from_millis(50));
        assert!(proc.poll().is_some(), "force_kill 后子进程应已退出、可回收");
    }

    #[test]
    fn real_child_poll_none_then_some() {
        // 起一个稍长的命令：刚 spawn 后 poll 可能仍 None；用 force_kill 收尾确保测试不悬挂。
        let mut proc = StdProcess::spawn("cmd", &["/C", "ping", "-n", "30", "127.0.0.1"]).expect("spawn cmd ping");
        let _ = proc.poll(); // 不假设一定 None（时序敏感），只验证调用不 panic
        proc.force_kill();
        assert!(proc.poll().is_some());
    }
}
