// §6-5：sidecar 进程级生命周期状态 → UI 横幅的纯映射（无 DOM、可单测）。
// 消费者遇未知 state 保守按崩溃处理：生命周期是错误类信号，绝不静默丢弃（对齐 contracts/sidecar_status.py）。
import type { SidecarStatus } from "../generated/sidecarStatus";

export type StatusBanner = { text: string; level: "info" | "warn" };

export function statusBanner(s: SidecarStatus): StatusBanner | null {
  switch (s.state) {
    case "starting":
    case "ready":
      return null; // 正常生命周期不出横幅（免噪声）。
    case "stopping":
      return { text: "sidecar 正在关闭…", level: "info" };
    case "stopped":
      return { text: "sidecar 已停止", level: "info" };
    case "crashed":
      return {
        text: `⚠ sidecar 崩溃（gen ${s.generation}）${s.detail ? "：" + s.detail : ""}`,
        level: "warn",
      };
    default:
      // 未知状态（协议演进/异常）：保守按崩溃提示，不静默。
      return { text: "⚠ 未知 sidecar 状态（按崩溃保守处理）", level: "warn" };
  }
}
