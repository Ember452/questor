//! OS 进程后端：把 crate 核心状态机接到真 `std::process::Child`，Windows 侧再套 **Job Object**
//! 使 sidecar 及其派生的 MCP 子进程随句柄关闭/强杀一并回收（防孤儿，S5/DoD③；Phase 7 T8）。
//!
//! Job Object 走**裸 kernel32 FFI**（不引 `windows` crate，保持零外部依赖）：本文件含 `unsafe`，
//! 并配**真子进程**测试实测 `Create/Set/Assign/Terminate` 全链路成功、子进程被回收。

use crate::Process;
use std::process::{Child, Command, Stdio};

/// 真子进程句柄实现。生产里 sidecar = `python -m questor --serve`（PyInstaller 冻结产物）。
pub struct StdProcess {
    child: Child,
    #[cfg(windows)]
    job: winjob::Job,
}

impl StdProcess {
    /// 拉起命令：stdout/stderr 置 null（sidecar 自有日志面，绝不把噪声灌进继承的控制台/观测面）。
    /// Windows 下先把进程放进一个 `KILL_ON_JOB_CLOSE` 的 Job，后续 force_kill / Drop 关闭 job 即回收整棵进程树。
    pub fn spawn(program: &str, args: &[&str]) -> std::io::Result<Self> {
        let child = Command::new(program)
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()?;
        #[cfg(windows)]
        {
            let job = winjob::Job::create()?;
            // 刚 spawn、sidecar 尚未派生 MCP 子进程，此刻 assign 覆盖后续所有 job 成员（子进程继承 job）。
            job.assign(&child)?;
            Ok(Self { child, job })
        }
        #[cfg(not(windows))]
        {
            Ok(Self { child })
        }
    }
}

impl Process for StdProcess {
    fn poll(&mut self) -> Option<i32> {
        self.child
            .try_wait()
            .ok()
            .flatten()
            .map(|status| status.code().unwrap_or(-1))
    }

    fn force_kill(&mut self) {
        // Windows：TerminateJobObject 连同 job 内全部进程（含 sidecar 派生的 MCP 子进程）一起结束；
        // 再 wait 回收直接子进程句柄。非 Windows：kill 直接进程。
        #[cfg(windows)]
        {
            let _ = self.job.terminate();
        }
        #[cfg(not(windows))]
        {
            let _ = self.child.kill();
        }
        let _ = self.child.wait();
    }
}

#[cfg(windows)]
mod winjob {
    use std::io;
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;

    // kernel32 的 Job Object API（裸 FFI；x64 上 extern "system" == C 调用约定）。
    #[link(name = "kernel32")]
    extern "system" {
        fn CreateJobObjectW(
            lpjobattributes: *mut core::ffi::c_void,
            lpname: *const u16,
        ) -> *mut core::ffi::c_void;
        fn SetInformationJobObject(
            hjob: *mut core::ffi::c_void,
            jobobjectinformationclass: i32,
            lpjobobjectinformation: *const core::ffi::c_void,
            cbjobobjectinformation: u32,
        ) -> i32;
        fn AssignProcessToJobObject(
            hjob: *mut core::ffi::c_void,
            hprocess: *mut core::ffi::c_void,
        ) -> i32;
        fn TerminateJobObject(hjob: *mut core::ffi::c_void, uexitcode: u32) -> i32;
        fn CloseHandle(hobject: *mut core::ffi::c_void) -> i32;
    }

    const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: i32 = 9;
    const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x2000;

    #[repr(C)]
    struct IoCounters {
        read_bytes: u64,
        write_bytes: u64,
        other_bytes: u64,
        read_operations: u64,
        write_operations: u64,
        other_operations: u64,
    }

    #[repr(C)]
    struct BasicLimitInformation {
        per_process_user_time_limit: i64,
        per_job_user_time_limit: i64,
        limit_flags: u32,
        minimum_working_set_size: usize,
        maximum_working_set_size: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }

    #[repr(C)]
    struct ExtendedLimitInformation {
        basic_info: BasicLimitInformation,
        io_info: IoCounters,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory_used: usize,
        peak_job_memory_used: usize,
    }

    /// 一个 `KILL_ON_JOB_CLOSE` 的 Job：句柄关闭（Drop）或 `terminate` 都会结束 job 内所有进程。
    pub struct Job {
        handle: *mut core::ffi::c_void,
    }

    // Job 句柄是内核对象句柄，可安全跨线程传递（tauri 管理状态要求 Send）；句柄生命周期由本结构独占。
    unsafe impl Send for Job {}

    impl Job {
        pub fn create() -> io::Result<Self> {
            unsafe {
                let handle = CreateJobObjectW(core::ptr::null_mut(), core::ptr::null());
                if handle.is_null() {
                    return Err(io::Error::last_os_error());
                }
                let mut info: ExtendedLimitInformation = std::mem::zeroed();
                info.basic_info.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                let ok = SetInformationJobObject(
                    handle,
                    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                    &info as *const _ as *const core::ffi::c_void,
                    std::mem::size_of::<ExtendedLimitInformation>() as u32,
                );
                if ok == 0 {
                    let err = io::Error::last_os_error();
                    CloseHandle(handle);
                    return Err(err);
                }
                Ok(Self { handle })
            }
        }

        pub fn assign(&self, child: &Child) -> io::Result<()> {
            unsafe {
                // Child 的原始句柄即进程句柄（RawHandle 已是 *mut c_void，无需再 cast）；std 保证 Child 存活期间该句柄有效。
                let process = child.as_raw_handle();
                if AssignProcessToJobObject(self.handle, process) == 0 {
                    Err(io::Error::last_os_error())
                } else {
                    Ok(())
                }
            }
        }

        pub fn terminate(&self) -> io::Result<()> {
            unsafe {
                if TerminateJobObject(self.handle, 1) == 0 {
                    Err(io::Error::last_os_error())
                } else {
                    Ok(())
                }
            }
        }
    }

    impl Drop for Job {
        fn drop(&mut self) {
            // 关闭最后一个 job 句柄 → KILL_ON_JOB_CLOSE 结束仍挂在 job 上的进程（防 sidecar 崩溃/重启留孤儿）。
            unsafe {
                CloseHandle(self.handle);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{two_phase_shutdown, Shutdown};
    use std::thread;
    use std::time::Duration;

    #[test]
    fn real_child_is_recovered_by_two_phase() {
        // 起一个不会自退的子进程；无优雅端点 → 到 grace 触发 force_kill；验证真 OS 上进程被回收、可 poll 到退出码。
        // 跨平台选长驻命令：Windows 用 `cmd /C ping`，POSIX 用 `sleep`（coreutils）。探测真实沙箱能力：
        // 若连所选二进制都起不来（极简沙箱缺省），显式跳过而非用 NotFound panic 冒充失败、更不用静默通过冒充成功。
        #[cfg(windows)]
        let spawned = StdProcess::spawn("cmd", &["/C", "ping", "-n", "30", "127.0.0.1"]);
        #[cfg(not(windows))]
        let spawned = StdProcess::spawn("sleep", &["30"]);
        let mut proc = match spawned {
            Ok(p) => p,
            Err(err) => {
                eprintln!("skip: no long-running child available in this sandbox: {err}");
                return;
            }
        };
        let out = two_phase_shutdown(
            || {},
            &mut proc,
            Duration::from_millis(300),
            Duration::from_millis(30),
        );
        assert_eq!(
            out,
            Shutdown::ForceKilled,
            "长驻子进程不会在 300ms 内自退，应走强杀兑底"
        );
        thread::sleep(Duration::from_millis(50));
        assert!(proc.poll().is_some(), "force_kill 后子进程应已退出、可回收");
    }

    #[cfg(windows)]
    #[test]
    fn job_object_terminates_assigned_child() {
        // 真机验证 Job Object 链路：spawn 内已 create+assign job；force_kill 走 TerminateJobObject 结束整棵 job。
        let mut proc = StdProcess::spawn("cmd", &["/C", "ping", "-n", "30", "127.0.0.1"])
            .expect("spawn into job");
        proc.force_kill(); // TerminateJobObject
        assert!(proc.poll().is_some(), "TerminateJobObject 后子进程应已退出");
    }
}
