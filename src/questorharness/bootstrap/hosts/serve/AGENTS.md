# serve — Agent Contract

职责：进程内 serve 宿主。`routes.py` 把请求映射到 runtime / authority；`wire.py` 把 StreamEvent 编码成帧；`broadcaster.py` 管 seq 与有界重放；`eventstream.py` 定 SSE 字节；`authority.py` 管单写者租约与三模态提示；`host.py` 装配并把渲染器注入 `handle_line`。
不负责：引擎与回合循环（`engine/`、`runtime/`）、提交链本体（`bootstrap/runtime.py` 的 `handle_line`）、会话存储（`platform/session_storage`）。本包不写业务策略。
公开入口：`ServeHost` / `Authority` / `MemoryTransport` / `Router` / `WireEncoder` / `Broadcaster`（见 `__init__.py`）。
拥有的数据：一次进程内的回合租约、提示 Future 表、帧重放窗口（8MB 有界）；**不拥有**会话快照。
允许依赖：本包在 bootstrap 层，可 import 任何下层；`routes.py` 不得 import aiohttp（传输适配在后续 `http_server.py`）；`wire.py` 不得 import broadcaster。
不变式：宿主**接收**已装配的 `RuntimeBundle`、不构造它；`seq` 只由 broadcaster 分配；拒绝码只出 `refusals` 白名单；`wire_types.py` 由 `scripts/codegen/gen_wire_py.py` 生成，**禁止手改**。
测试：`uv run pytest tests/unit/bootstrap/hosts/serve tests/e2e/test_serve_host_smoke.py -q`
关键文件：`routes.py`（端点）、`host.py`（装配与回合调度）、`authority.py`（租约/幂等/提示）、`broadcaster.py`（seq/重放）、`wire.py`（帧编码）
