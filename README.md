# Questor

> **本地优先的自研超级智能体运行时（Agent Harness）+ 桌面通用个人 Agent。**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
![Python](https://img.shields.io/badge/Python-3.13-blue)
![Status](https://img.shields.io/badge/status-pre--alpha-orange)
<!-- CI 徽章等 .github/workflows 落地后再接 -->

**状态：设计/骨架阶段（pre-alpha）**——架构文档已完备，正在进入实现（见 ROADMAP 的 P0）。暂无可运行版本。

## 这是什么

Questor 是一个从零构建的 **Agent Harness**（运行时底座）+ 其上**可插拔的 Agent 策略层**：

- **Harness**：turn 循环驱动、唯一可信状态模型、事件协议、工具路由、权限三态 + 沙箱、持久化/断点续传。
- **Agent 层**：规划/ReAct、反思、记忆策略、提示词——可注册/热替换/A·B，换算法不动内核。
- **模型**：经 LiteLLM 多供应商（BYOM）；**桌面**：Tauri v2 + Web 前端，后端为 Python sidecar。

## 特性（路线图）

- 🧠 分层解耦的 Agent Harness（harness ↔ policy ↔ provider/shell）
- 🧩 工具 + Skills + MCP，统一权限/账本
- 💾 事件溯源 + 断点续传 + 可恢复上下文压缩
- 🗂 三层长期记忆 + Deep Dream 蒸馏
- 🖥 桌面（Tauri）+ CLI + **OpenAI 兼容 API**（鉴权外部 lane；**仅文本模态**——非文本/语音请求归一化拒绝而非静默降级，[ADR-0036](docs/adr/0036-p6-dropped-from-roadmap.md)/[ADR-0044](docs/adr/0044-non-text-content-normalize-reject.md)），多端共享同一事件协议
- 🔌 策略/工具/技能/MCP 可热插拔（薄插件宿主 + 故障熔断、cordis 式注册形状而非通用 DI；策略 registry 支持热替换/A-B），换能力不动内核（[ADR-0045](docs/adr/0045-policy-registry-and-run-policy-ref.md)/[ADR-0046](docs/adr/0046-capability-hot-plug-host.md)）

## 文档

- 定位与蓝图：[docs/VISION.md](docs/VISION.md)
- 全局路线图/阶段：[docs/ROADMAP.md](docs/ROADMAP.md)
- 仓库结构：[docs/STRUCTURE.md](docs/STRUCTURE.md)
- 架构设计（分层/状态/事件/工具/循环/策略/记忆/红线）：[docs/design/](docs/design/)
- 架构决策记录：[docs/adr/](docs/adr/)

## 快速开始

> 尚无可运行版本。P1（最小可跑循环）落地后此处会更新为 `uv sync && uv run questor`。

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。设计文档先行、每个改动带可验证 DoD。

## 安全

见 [SECURITY.md](SECURITY.md)。

## 鸣谢（设计参考）

Questor 为独立自研实现，架构设计在研究以下优秀开源项目的机制后完成：hermes-agent、wuu、DeepCode、CowAgent、MetaGPT、cordis 等。它们仅作**设计参照**，代码不来自它们。

## 许可证

[MIT](LICENSE) © 2026 Ember452
