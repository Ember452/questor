# ADR-0044: 非文本/语音 content part 归一化拒绝（P9 硬判据）

- 状态：🚧（2026-10-18，P9 开工前置门；实现见 [`../plan/09-p9-openai-plugin-host.md`](../plan/09-p9-openai-plugin-host.md) T7）
- 背景：[`ADR-0036`](./0036-p6-dropped-from-roadmap.md) 整阶段移除 P6（多模态/语音），并**决策 5 给 P9 新增一条硬判据**：OpenAI 兼容面收到 `image_url`/`input_audio` 等非文本 content part 或语音类请求时，必须**归一化拒绝**——明确的"provider 能力不支持"错误 + 经 [`ADR-0028`](./0028-pairing-gate-and-provider-fault-normalization.md) 的故障归一终态；**绝不崩、绝不静默降级成纯文本继续跑**。ROADMAP §1.5 P9 备注同步钉死。现状事实：本仓 `contracts/state_schema.py` 的 `ContentBlock` 仅 `text`/`tool_use`/`tool_result`，全 `src/` 对 `voice|audio|tts|asr|vision|modalit` 零命中（`ADR-0036`:11 核实）——即 questor 根本无能力表示多模态块。
- 决策：
  1. **surface 层 fail-fast（主路径）**：OpenAI 面解析入站 `messages[].content` 的每一 part，若 `type ∉ {"text"}`（如 `image_url`/`input_audio`/`file`/语音类），**不起 run、不建 Command**，直接返回 HTTP 400 的 OpenAI error object：`{"error":{"type":"invalid_request_error","code":"unsupported_modality","message":"provider capability not supported: <part-type>"}}`。这是**协议级输入校验**（在适配器边界、非状态写），不违 C16/C14。
  2. **单一错误语义**：错误形状复用 [`ADR-0028`](./0028-pairing-gate-and-provider-fault-normalization.md) 同一分类器口径——`contracts/errors.py::classify_provider_error` 的命名空间，不另立第二套错误文案。**OpenAI-wire `error.code` 是适配器作用域字符串**（给外部 SDK），与 questor `ErrorKind` 分两层、不混。
  3. **契约 additive 一等 kind**：`contracts/errors.py::ErrorKind` 增 **`UNSUPPORTED_MODALITY = "unsupported_modality"`**（现 enum 无此项；HTTP 400 原落 `FORMAT_ERROR`，但 `ADR-0036` 决策 5 要"明确能力不支持"，故单列一等 kind、`retryable=False`）。属稳定错误命名空间的**增量**、走本 ADR、不破既有 kind 语义。
  4. **defense-in-depth（兜底路径）**：若某多模态块经中间/工具/委派路径意外到达唯一 provider 调用点 `kernel/loop.py::_stream_turn`（理论不该发生，因 `ContentBlock` 无法表示），仍由 `classify_provider_error` 归一为 `run_failed`（`ErrorKind.UNSUPPORTED_MODALITY`、不可重试），**绝不穿出 turn 循环带崩宿主**（承 C19/[`ADR-0028`](./0028-pairing-gate-and-provider-fault-normalization.md)）。
  5. **能力叙述诚实**：`README.md` / `docs/VISION.md` 能力叙述明确"当前仅文本模态"（`ADR-0036` 决策 5 强制项，不是可选项）。
- 后果：
  - 正面：外部客户端拿到的是一眼可懂的"能力不支持"、而非静默丢图后答非所问、更非进程崩溃；错误语义与全仓 provider 归一单一对齐；协议/状态**零破坏性改动**（仅 additive 一 kind）。
  - 代价 / 需持续守：未来若真上多模态（`ADR-0036` 决策 4 的接缝扩展路径），此 kind 与拒绝分支要改道为 provider 能力声明前置校验（`ADR-0036`:45 提到的 P6 检查项 1）；本 Phase 不做，保持"仅文本"诚实边界。
- 备选(被否)：
  1. 静默丢弃非文本 part、只取 `text` 继续跑 run → 否（`ADR-0036` 决策 5 明令"绝不静默降级成纯文本继续跑"；会造成用户看不到、模型答非所问的隐性错）。
  2. 让多模态块穿到 provider 由上游 4xx 崩宿主 → 否（重演 `ADR-0028` 修前的崩溃事故）。
  3. 为多模态新立一套独立错误文案/类型 → 否（与 `classify_provider_error` 并存 = 错误语义第二真源，违 C15）。
  4. 现在就加 vision/ASR provider 把请求"接下来" → 否（`ADR-0036` 整阶段移除 P6；本 Phase 只落归一拒绝硬判据）。
- 关联：`ADR-0036` 决策 5（义务来源）、`ADR-0028`（归一路径）、`ADR-0043`（承载此拒的 OpenAI 面）；HARD-CONSTRAINTS C14（适配器边界校验不下沉内核业务）/C15（错误语义单一真源）/C19（provider 故障不崩宿主）/C6（additive kind）；`docs/ROADMAP.md` §1.5 P9 备注；peer：CowAgent `openai_compat.py`（请求校验/路由形状）。
