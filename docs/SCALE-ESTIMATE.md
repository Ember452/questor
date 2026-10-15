# Questor 规模估算与扩展路线

> **工程估算、区间、不是承诺**。用途：给里程碑"大小感"，随范围收敛/扩张调整。

## 1. 参考锚点（同 workspace 兄弟项目，粗估含 tests）

| 项目 | 主语言 | LOC | 与 questor 关系 |
|---|---|---|---|
| CowAgent | Python | 30k–45k | 更窄（无 Tauri / 无事件溯源 / 无三层记忆深度） |
| MetaGPT | Python | 50k–80k | 框架类、无桌面壳 |
| DeepCode | Py+Rust+TS | **120k–250k** | **与 questor 最像**（harness+sidecar+Tauri） |
| wuu | Go+TS | 200k–400k | 覆盖面最广、70+ 子包 |
| hermes-agent | Py+TS+Rust | 400k–700k | 极端健壮性，不必对标 |

Questor 落在 **CowAgent 与 DeepCode 之间、向 DeepCode 靠**。

## 2. P10 完成后代码量估算

| 类别 | LOC 范围 |
|---|---|
| Python 后端（不含测试） | 30k–50k |
| TS 前端（desktop/web） | 15k–25k |
| Rust 壳（src-tauri） | 1.5k–3k |
| Wire schema / SQL / yaml / config | 2k–4k |
| **有效代码小计** | **~60k–100k** |
| 测试（unit + integration + evals ≈ 0.7–1.1x 码量） | 35k–65k |
| 文档（md，含设计/指南/API/CHANGELOG） | 30k–50k |
| **合计（含测试与文档）** | **~130k–200k** |

粗略文件数：`src/*.py` 250–450；`web/*.ts(x)` 150–250；`src-tauri/*.rs` 30–60；`tests/` 400–700；`docs/` 80–150。

## 3. Commit 数估算（按 AGENTS 细粒度纪律）

| 阶段 | 估算 |
|---|---|
| 设计文档（当前） | ~50 |
| P0 接口骨架 | 30–50 |
| P1 最小循环 | 40–80 |
| P2 工具+权限 lite | 80–150 |
| P3 事件溯源+resume | 60–120 |
| P4 三层记忆+蒸馏+检索 | 100–200 |
| P5 Skills+MCP | 80–150 |
| P6 多模态+语音（10+ provider） | 80–150 |
| P7 Tauri 桌面 | 150–250 |
| P8 多 agent+DAG | 80–150 |
| P9 OpenAI 兼容+插件宿主 | 100–180 |
| P10 加固（可恢复压缩/回归网/observability/CI/供应链） | 150–300 |
| 横切：重构/CI 修补/依赖 bump/文档维护 | 100–200 |
| **合计** | **~1100–1800 条**（中位 ~1400–1500；极细粒度可上 2500） |

## 4. 影响估算的杠杆
- **收窄到 80k–100k / ~1000 commits**：v1 只做 top-3 语音 provider、桌面 UI 保持"够可用"、evals 集 20 条任务封顶、P8/P9 简化。
- **扩到 150k+ / 2000+ commits**：把 P8/P9/P10 做透（真多 agent + 完整热插宿主 + 全套 CI lane + 完整可恢复压缩）。

## 5. 时间维度（非承诺）
按业余节奏 5–10 commit/日 → P10 收口 **6–12 个月**；全职显著更快。用户已定"不计工作量、长期维护"。

## 6. P10 之后仍可做的扩展（架构预留、**加挂新件、不动内核**）

- **新策略（L4，加/换不动内核）**：ToT / LATS / GoT 多算法族；反思/自我进化（Curator 式）；垂直 preset（研究 / 编码 / 运维 / 客服 / 教育等）。
- **新能力（L3）**：更多内置工具；**GUI / computer-use agent**（参考 Agent-S）；行业 MCP 集；Skills Marketplace / Hub。
- **新 Surface（L6，只订阅事件协议）**：Web 版（浏览器连远程 questor）；IDE 插件（VSCode / JetBrains）；移动客户端；浏览器扩展；IM 群机器人；cron/自动化面板。
- **新 Provider 侧（L5）**：更多模型 / 嵌入 / 语音 / 图像 / 视频；BYOM 私有网关；成本预算治理。
- **多 agent / 编排深化（P8 起步）**：swarm / crew-like pipeline、supervisor-worker 层级、跨机协同。
- **知识库 / RAG**（当前最高准则"先不做"）：向量库 + ingestion 通道已在，届时可直接接入。
- **观测与治理**：trace 回放 UI、eval 面板、成本看板、审计合规。
- **部署形态**：单机 → 家用服务器 / NAS → 团队共享 → 云端多租户。

## 7. 会触天花板、需**新 ADR** 才能启动的深改
- **跨机 exactly-once / 分布式排序 / 租约**（C12 硬骨头，hermes/wuu 都在啃）。
- **多租户 SaaS 化**：鉴权、隔离、成本分摊、并发写模型。
- **端侧全本地**：去 LiteLLM 或加 llama.cpp / Ollama 本地 provider + 本地嵌入/语音。
- **强合规/审计**：零上云 + 可验证审计链。

> 关键：**六节的扩展基本都在"挂新 PolicyPort / 新 ToolSpec / 新 Surface / 新 Provider"这些早锁的接缝上**——加不改，符合 C11 演进策略。第七节才需要新的架构决策。
