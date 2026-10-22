# ADR-0001: 从零自研，questor 为全新仓库

- 状态：✅（2026-10-15）
- 背景：早期路线是"把 CowAgent 增量移植成 questor"。随后方向转为**自己造一个长期演进、可超大规模扩展的桌面通用个人 Agent**。用户已删除 GitHub 旧库、重建全新 questor，明确与旧移植无关。
- 决策：**不从任何现成项目复制代码**；从零自研 Agent Harness + Agent 策略层。CowAgent/hermes/wuu/DeepCode/MetaGPT/cordis 等**只作设计参照与失败模式清单**，不搬代码。旧移植的一切决策（LinkAI→LiteLLM 替换、零 cow、src 包化移植、里程碑 M0-M9 等）**作废**。
- 后果：
  - ✅ 拿到真正属于自己的核心资产（harness），演进无历史包袱。
  - ⚠️ 自研 harness 是"从 0 最容易踩坑"的一层——用 §"上游参照→失败模式清单→再自研"的纪律对冲（见 HARD-CONSTRAINTS / 设计文档）。
  - 需持续守住分层红线，否则架构会随迭代腐化。
- 备选(被否)：
  - 增量移植 Cow（快、少踩坑，但非自研、且方向已变）→ 否。
  - 以某框架(LangGraph 等)为骨架半自研 → 否（"自研框架含金量"与掌控度不足）。
- 关联：[`../VISION.md`](../VISION.md)、[`../design/00-layering.md`](../design/00-layering.md)。
