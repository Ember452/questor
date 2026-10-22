# ADR-0032: P7 sidecar serve 接线与进程边界落地（D-P7-B）

- 状态：✅（2026-10-17）
- 背景：[`ADR-0007`](./0007-transport.md) 定了"统一 HTTP+SSE、Tauri 只内嵌 webview、禁私有 IPC 协议"的方向，但落地细节一直悬空：仓库只有 `surfaces/http_sse.py` 的 `EventServer`/`create_app` 类，**没有生产入口去跑 uvicorn**（`__main__.py` 仅 REPL/`--resume`/`--list`/`--dream`），也没有"桌面壳如何把 Python harness 当独立进程拉起、拿到端口、防陈旧连接"的口径。P7 T1 要把这条 sidecar serve 面接通，触及**新 L6 面 + 进程边界 + 端口/bootstrap 契约**，属难回退决策，先记 ADR 补 ADR-0007 的落地细节。
- 决策：
  - **传输与进程边界**：Rust 壳把 Python harness 作为**独立 sidecar 进程**，二者**仅经 HTTP+SSE 事件协议**（loopback）通信，**严禁进程内直调 Python、严禁私有 Tauri event 协议**（承 ADR-0007 / STRUCTURE S5）。就绪探测从"参考仓的 stdin `initialize`"改为**轮询 `127.0.0.1` 临时端口 + 首帧 SSE**（ADR-0007 无进程内握手可用）。
  - **端口**：uvicorn bind `127.0.0.1:0`（OS 分配临时口），启动后读**实际端口**；**绝不 bind `0.0.0.0`**（本地 IPC，无网络出口，呼应 C12）。实现上先自建一个 bound socket 拿 `getsockname()` 端口、再以 `sockets=[sock]` 交给 uvicorn，避免"起服务后再猜端口"的竞态。
  - **generation bootstrap**：每次（重）起 sidecar 记一个进程内单调 `generation`，连同 `port`/`pid` 写一份**本地 bootstrap 文件**（供 Rust 注入 webview、并作为"陈旧连接栅栏"的比对基）。**bootstrap 是进程启动握手、不进事件协议、不是跨进程第二真相**。
  - **装配落点（开工当场校正，reality-wins）**：`scripts/check_layering_ast.py` 的 `FORBIDDEN_IMPORTS["surfaces"]` 明禁 `questor.providers.store_sqlite`/`store_memory_sqlite`/`subprocess`。故 **具体 store（`SQLiteStore`/`SQLiteMemoryStore`）实例化留在组合根 `__main__.py --serve` 分支**（与 REPL 同构、本就 import 具体适配器、且 `__main__` 不在分层扫描内）；`surfaces/serve.py` **只接收注入的** `EventServer`/`StorePort` 抽象 + 跑 uvicorn + 读端口 + 写 bootstrap，**不 import 任何具体 store 实现**（守 S6/C4）。
  - **日志装配口径**：serve 入口必调 `surfaces._assembly.assemble_logging()`（组合根唯一装配口径），**不自配 `configure_logging`**（承 Issue #138 教训：两个生产入口曾各配各的）。
- 后果（正面 / 代价 / 需持续守）：
  - 正面：桌面/网页/移动共用一套 HTTP+SSE 客户端；断线可 `after_seq` 重连；sidecar 生命周期有明确端口/代次锚点；分层守卫不破。
  - 代价：Rust 侧需实现"轮询端口就绪 + 首帧 SSE 探活 + generation 栅栏"（搬参考仓**形状**、不搬 stdio **传输**）；bootstrap 文件需定义读写与陈旧清理。
  - 需持续守：任何"为图快在 Rust 里进程内调 Python / 造私有 event 面"都违 S5/ADR-0007，由 T9 瘦客户端/进程边界守卫拦。
- 备选（被否）：
  1. stdio JSON-RPC sidecar（照搬参考仓 DeepCode 传输）→ 否：与 ADR-0007 HTTP+SSE 铁律冲突，桌面/远程无法复用同一客户端。
  2. 私有 Tauri IPC event 协议 → 否：ADR-0007 已否（为桌面造一套、web/远程要重造）。
  3. 让 `surfaces/serve.py` 自己装配 `SQLiteStore` → 否：违 `check_layering_ast` FORBIDDEN_IMPORTS[surfaces]、违 C4/S6"surfaces 不 import store 实现"。
  4. bind 固定端口或 `0.0.0.0` → 否：固定端口冲突、`0.0.0.0` 开网络出口违本地 IPC/C12。
- 关联：[`ADR-0007`](./0007-transport.md)（本 ADR 落其细节）、[`ADR-0013`](./0013-run-command-inbox.md)（命令入口不变）、`STRUCTURE` S5/S6/§9（sidecar 三段式）、`HARD-CONSTRAINTS` C1/C4/C12/C14/C16、`docs/plan/07-p7-desktop-shell.md` §0.3 D-P7-B / T1。
