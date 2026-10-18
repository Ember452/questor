# ADR-0036: P6（多模态/语音）整阶段从路线图移除，后续序列 = P8 → P9 → P10

- 状态：✅（2026-10-18）
- 背景：`docs/ROADMAP.md §1` 的 P6 行同时覆盖两半能力——**图/文件识别** 与 **语音 ASR/TTS（全走 LiteLLM）**，
  §2 把它列为"v1 后"。P7 桌面壳已经 PR #145 合入 `main`（`6d2b465`），v1（P0–P4 + P7，§2/§4 节点 C）
  的能力面与对外门面已齐，排期压力转到 P8/P9/P10。此时重审 P6 的性价比，三条事实成立：
  1. **依赖图上是叶子**：P8 进入条件 = P4、P9 = P7、P10 = P3 起持续（§1 表 P8/P9/P10 行），**没有任何 Phase 消费 P6 的产出**；
     P7 对抗审计亦已确认桌面壳"不含 P6/P8+"合规（`docs/audit/P7-review-2026-10-17.md:38`）。
  2. **占位从未落地**：§1.5「契约占位在前期」(R2) 与 `docs/delivery/P1-completion-report.md:110`、`docs/plan/01-p1-minimal-loop.md:44,112`
     均宣称"P0-P2 先写多模态事件 `type` 占位"，但实况是 `src/questor/contracts/events.py:251-273` 的 20 个 `EventType`
     **一个语音/图像类都没有**，全 `src/` 对 `voice|audio|tts|asr|vision|attachment|modalit` 零命中。
     → 移除 P6 **不产生孤儿占位/契约残骸**，同时暴露一处需回写的文档-代码偏差（本 ADR 就地记账，见"后果"③）。
  3. **成本与可验证性最差**：`docs/SCALE-ESTIMATE.md §3`（阶段表）估 P6 = **80–150 commit/文件 + 10+ provider**，
     且其 DoD 两半都压在**外部云服务与真凭据**上（vision/ASR/TTS 真实调用）——恰是当前标 UNVERIFIED 债务最重、
     本机最无法证伪的一类；§4 已把"top-3 语音 provider"列为收窄总量的首要杠杆。
     产品面真实的缺口在**编排（P8）与对外接口/插件宿主（P9）**，不在输入模态。
- 决策：
  1. **P6 整行从阶段序列移除**（语音 + 图像**全砍**，不做半保留）。§1 表 P6 行改为"已移除（本 ADR）"并留指针；
     `plan/06` 从未写过，无需作废文档。
  2. **编号不重排**：P7–P10 保持原号，P6 留空号。理由：P7–P10 已作为锚点散布在 ADR-0029~0035、已合并分支名
     `feat/p7-desktop-shell`、`docs/audit/*`、`docs/delivery/*`、`CHANGELOG.md`、`docs/STRUCTURE.md` 各处；
     重排等于**回改历史快照**且与既成事实（P7 已合入）矛盾，引用失真成本远大于表格美观收益（AGENTS §3）。
  3. **后续序列钉为 P7（已完成）→ P8 → P9 → P10**；P10 仍是横切收口（回归评测网 / 可恢复压缩 / observability 刀 3）。
  4. **逆转路径写死为"接缝上的按需扩展，不再占 Phase 编号"**：将来若确有真实需求，按 ROADMAP §5 另记新 ADR，
     落点已经确定、无需重新设计——**L5 新增 vision/ASR/TTS provider 端点 + L6 接收与投递端点 + 事件面按
     `docs/design/02-event-protocol.md §6/§7` 只加 `type`（不碰信封/关联键/终止序）+ 大载荷复用
     [`ADR-0019`](./0019-bounded-artifact-projection.md) 的有界 artifact 指针**。
     `SCALE-ESTIMATE §6` 早已把"语音/图像/视频 provider"归入"P10 之后可加挂、不动内核"的扩展清单，本决策与之同一归口。
  5. **P9 新增一条硬判据**（砍掉 P6 后唯一需要补的工程约束）：OpenAI 兼容面收到 `image_url` / `input_audio` 等
     非文本 content part 或语音类请求时，必须**归一化拒绝**——明确的"provider 能力不支持"错误 + 经
     [`ADR-0028`](./0028-pairing-gate-and-provider-fault-normalization.md) 的故障归一终态；**绝不崩、绝不静默降级成纯文本继续跑**。
     写进 `plan/09` 的前置门，并在仓库根 `README.md` / `docs/VISION.md` 的能力叙述里诚实反映"当前仅文本模态"。
- 后果：
  - 正面：直接省掉 80–150 文件与 10+ provider 的外部依赖验证；v1 后的人力全部压在"要动内核接缝的难做项"
     （P8 编排/DAG、P9 宿主/DI、P10 加固）上，而不是最容易后加的一层；协议与状态**零改动**——
     "只加事件、不改信封"本就是为这种场景立的验收判据（VISION §4 `:57`）。
  - 代价：① **对外能力口径收窄**——"发图能识别"在今天已接近桌面 agent 的用户默认预期，砍掉就必须同步把产品叙述
     改诚实（决策 5 因此是强制项，不是可选项），否则用户在 P9 之后撞墙比一开始不做更糟；
     ② 语音链路的 10+ provider 工作量并非"消失"，只是从**必经阶段**降为**按需扩展**；
     ③ **需回写的文档偏差**：§1.5 R2 的"多模态占位"一句从未兑现——本轮把它从"待兑现承诺"改为"已随 P6 移除、无需补"，
     历史交付报告（P1 `:110`）与 `plan/01` 的原文**不回改**，只在本 ADR 记账（与 `CHANGELOG.md` 既有纪律一致：
     不改阶段结论、不回改历史验收判据）。
  - 需持续守：`docs/design/02-event-protocol.md §7`（`:71`）仍以"语音附件→`voice_attached`"作**生长场景例证**，
     这是协议纪律的检验样本、**不是功能承诺**，保留原文；`docs/audit/PROMPTS.local.md` 的 P6 段（`:204`）标注停用备查
     （其检查项 1/3/5/6——provider 能力声明前置校验、CoT 不外泄、大内容走指针、错误分类独立 reason——
     对纯文本路径同样有效，将来做按需扩展时直接复用）。
  - 顺带发现（**不属本决策、不回改**，仅登记）：`CONTRIBUTING.md:14` 让人 `uv sync --extra im|voice|browser|docs`，
     但 `pyproject.toml` 根本没有 `[project.optional-dependencies]`——这四个 extras 从来不存在，属早于本决策的
     死指针（AGENTS §3：无关漂移只提及不顺手改）；因本决策让 `--extra voice` 更容易被误读为"语音已可用"，故在此点名，
     宜另开 GitHub Issue 处理。
- 备选（被否）：
  1. **只砍语音、保留图像识别**：否——用户明确拍定"完全跳过"；且图像同样把 DoD 压在外部 provider 真调用上，
     留半条 P6 就是留一个半途阶段的验证成本与一个易被误读为待办的编号。日后真有需求，走决策 4 的接缝扩展比现在养着
     "P6(小)" 更干净。
  2. **保留 P6 编号、只标"按需/延后"**：否——编号只要还挂在 §1 序列表上，下一个会话就会照着表把它当待办开工，
     与"移除"的真实意图冲突；移行 + 留空号注释更不易误读。
  3. **重排为 P6–P9 补齐编号**：否——见决策 2。
  4. **直接在 §2 清单里删掉、不记 ADR**：否——违 ROADMAP §5 与 AGENTS §5.5「阶段增删/跨阶段移动 → 先记 ADR 再改路线图」；
     本 ADR 即那道前置门。
- 关联：`docs/ROADMAP.md` §1（P6/P8/P9/P10 行）、§1.5（R2 占位口径、P9 备注）、§2（v1 范围）、§5（变更规则）；
  `docs/VISION.md` §4（可扩展验收 `:57`）、§8（"待拍（产品口径）"一条 → 已拍）；
  [`ADR-0019`](./0019-bounded-artifact-projection.md)（有界 artifact 载荷 = 逆转路径的现成件）、
  [`ADR-0028`](./0028-pairing-gate-and-provider-fault-normalization.md)（决策 5 的归一拒绝路径）、
  [`ADR-0029`](./0029-parallel-tools-deferred-beyond-p5.md)（同类"功能跨阶段移动先记 ADR"先例）、ADR-0012（分支/PR 门禁）；
  `docs/design/02-event-protocol.md` §6/§7；`docs/SCALE-ESTIMATE.md` §3/§4/§6；`docs/audit/PROMPTS.local.md` P6 段；
  `docs/audit/P7-review-2026-10-17.md:38`（P7 未提前塞 P6 能力的范围核验）。
