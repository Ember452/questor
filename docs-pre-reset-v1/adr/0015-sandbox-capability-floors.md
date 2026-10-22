# ADR-0015: OS capability floor 高于 permission mode，禁止静默降级

- 状态：✅（2026-10-15）
- 背景：Windows Job Object 只隔离/终止进程树，不提供文件系统写围栏；`none` 后端甚至没有可靠进程树隔离。若把后端探测成功误写成“已沙箱保护”，或在 `full_auto` 下让 mode 绕过缺失能力，会产生最容易造成不可逆损害的安全假象。
- 决策：
  - `SandboxPort` 从三个布尔升级为 `SandboxDescriptor`：backend、confinement、fences writes/network/process tree、workspace profile、绝对路径与限制说明。
  - 新增不可被 mode 突破的 capability floor：
    - 无可用后端：所有 exec 工具 deny；write 只能 ask + 工具内 containment + warning。
    - 只有 Job Object：exec 的已证明 read-only、无写形态、无重定向命令可 allow；其他命令至少 ask。
    - 无写围栏：write 至少 ask，`full_auto` 不可降为 allow。
    - seatbelt/bwrap 真实围栏：按 ToolSpec/risk/command analysis 正常 allow/ask/deny。
  - 未解析、动态程序、管道子命令、encoded command、`Invoke-Expression`、脚本块、进程替换等一律不得归类为 read-only。
  - 每次非 full confinement 都必须产生面向模型的 warning，明确“人工审批不是 OS 隔离”。
  - 给不了承诺的围栏时返回结构化错误/拒绝，绝不静默原样执行。
- 后果：Windows 上的可用性比“full_auto 全放行”更保守，但用户只会在真正缺少写围栏时看到审批；架构能长期诚实区分 screen、containment 与 OS sandbox。
- 备选（被否）：
  1. Windows write 一律 deny：本机 P2 DoD 不可达，并反向激励用户启用更危险的 full_auto → 否。
  2. Job Object 声称 exec 已沙箱：没有文件系统边界 → 否。
  3. full_auto 覆盖 capability floor：模式只是审批偏好，不能伪造 OS 能力 → 否。
  4. DeepCode 的 backend absent passthrough：把隔离缺失伪装成正常执行 → 否。
- 关联：ADR-0006、ADR-0014、ADR-0017；HARD-CONSTRAINTS C8/C9；[`../design/03-tool-interface.md`](../design/03-tool-interface.md) §4/§7/§11。
