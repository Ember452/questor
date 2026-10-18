// §6-5：进程级 sidecar_status → UI 提示的**纯映射**单测（无 DOM、真跑 vitest）。
// 生命周期是错误类信号：crashed/未知必出声，starting/ready 静默，stopping/stopped 轻提示。
import { describe, expect, it } from "vitest";

import { statusBanner } from "./status";
import type { SidecarStatus } from "../generated/sidecarStatus";

const st = (over: Partial<SidecarStatus>): SidecarStatus => ({ state: "ready", generation: 1, ...over });

describe("statusBanner", () => {
  it("crashed 必出声（含代次与 detail）", () => {
    const b = statusBanner(st({ state: "crashed", generation: 3, detail: "exit 1" }));
    expect(b).not.toBeNull();
    expect(b!.level).toBe("warn");
    expect(b!.text).toContain("崩溃");
    expect(b!.text).toContain("gen 3");
    expect(b!.text).toContain("exit 1");
  });

  it("starting/ready 静默（不出横幅）", () => {
    expect(statusBanner(st({ state: "starting" }))).toBeNull();
    expect(statusBanner(st({ state: "ready" }))).toBeNull();
  });

  it("stopping/stopped 轻提示（info）", () => {
    expect(statusBanner(st({ state: "stopping" }))?.level).toBe("info");
    expect(statusBanner(st({ state: "stopped" }))?.level).toBe("info");
  });

  it("未知状态保守按崩溃处理（生命周期不静默丢弃）", () => {
    const b = statusBanner(st({ state: "exploded" as unknown as SidecarStatus["state"] }));
    expect(b?.level).toBe("warn");
  });
});
