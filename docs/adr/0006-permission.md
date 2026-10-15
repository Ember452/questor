# ADR-0006: 权限三态决策一等 + 沙箱后端可插拔

- 状态：✅（2026-10-15）
- 背景：agent 必然"动电脑"（bash/写文件/浏览器），是 RCE 级面；权限若后补=重写循环。
- 决策：
  - **权限决策模型(allow/ask/deny 三态 + 通配 rules + 不可覆盖的敏感路径 denylist) 第一天进 L1/L2 为一等字段**；`ask`→`awaiting_approval` 状态 + 一条 HITL 事件。
  - **判定/封装是纯函数、在 Harness**（DeepCode harness 纪律）；**参数校验分两层**(json-schema + 权限/沙箱)，业务校验不下沉沙箱。
  - **OS 沙箱后端(seatbelt/bubblewrap/受限执行) 是可插拔实现 + 优雅降级**，v1 可先轻、后补真隔离。
  - mode/权限变更属 `Command`、走 reduce；**历史 tool_call 的 decision 不回溯**，只对未来生效。
- 后果：换沙箱后端不动上层、可审计；代价=v1 沙箱可能先弱（受限执行），需明确后续补。
- 备选(被否)：先做能力后补权限（改循环代价大、早期安全洞）→ 否。
- 关联：[`../design/01-state-model.md`](../design/01-state-model.md) §6、HARD-CONSTRAINTS C8/C9。
