# ADR-0002: 技术栈 — Python + Tauri v2 + LiteLLM + Python sidecar

- 状态：✅（2026-10-15）
- 背景：需一个长期可维护、可扩到桌面/网页/移动、且单人也能推进的栈。大脑是 agent 运行时（重生态、重迭代）。
- 决策：
  - **运行时/语言：Python**（LiteLLM、MCP 原生生态最肥；与参照项目同源好借鉴）。
  - **桌面：Tauri v2 + Web 前端(React/Svelte + TS) + Python 后端作为 sidecar 子进程**；UI 只当瘦客户端，经事件协议连后端。
  - **模型层：LiteLLM（SDK/网关）**做多供应商路由 + fallback + 成本；**引擎(harness)自研、模型借力**（②）；预留 BYOM（把别的 agent 当引擎）。
  - 存储：SQLite + 向量库（经 StorePort 封装）。
- 后果：
  - ✅ 一份 Web UI 复用到桌面/网页/移动；轻量单二进制；UI 与内核解耦（换壳/加端不动 harness）。
  - ⚠️ 要碰一点 Rust(sidecar/IPC)；系统 webview 偶有跨平台渲染差异。
- 备选(被否)：
  - Go 全栈（并发/类型强，但 agent 生态成本高、开发慢）→ 仅备选。
  - Electron（成熟但重、移动端弱）→ 次选，若嫌 Tauri 折腾可退。
  - 纯 Python GUI(PySide/Flet)（省语言但 UI 天花板与跨端差）→ 否。
- 关联：[`../design/00-layering.md`](../design/00-layering.md)、ADR-0007。
