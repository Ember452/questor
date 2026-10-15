# 阶段交付报告（Delivery Reports）

> 这里放**回头看**的文档：每个 Phase 实际交付了什么、最终架构长什么样、做了哪些取舍、还有哪些诚实边界。
> 与 `docs/` 其他目录的区别：
> - `design/` `adr/` `plan/` = **往前看**（要做什么、为什么这样定、打算怎么做）；
> - `audit/` = **对抗式挑刺**（哪里没做到）；
> - `delivery/`（本目录）= **交付快照**（做完了什么、以代码为准）。
>
> 想快速对别人讲清"这两个阶段到底干了啥"，读这里。

| 报告 | 一句话 | 状态 |
|---|---|---|
| [P0-completion-report.md](./P0-completion-report.md) | 八层包骨架 + 全签名契约 + 三道分层守卫 + 事件协议单一真源，**空而有形、不能跑** | ✅ 达成 |
| [P1-completion-report.md](./P1-completion-report.md) | 最小可跑循环：单模型 + `read` 一个工具 + 流式 + 可取消，把承重接缝一次砌到位 | ✅ 达成（含诚实边界） |
| [../plan/02-p2-tools-permission.md](../plan/02-p2-tools-permission.md) | P2 开工前修订基线：Command Inbox、PermissionCtx、capability floor、HITL、Shell IR、ProcessRunner、Artifact/Projection | 🚧 待实现 |

> 数字口径均来自 `docs/audit/` 之后的一次全量修复，报告撰写时实测复核：`pytest` 66 passed、`ruff` 全绿、`lint-imports` 4 契约 KEPT、`git log` 87 commits。
