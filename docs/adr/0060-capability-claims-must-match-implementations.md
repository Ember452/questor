# ADR-0060: 能力声明必须与实现同源；文档状态一致性进机守（收口）

- 状态：✅（2026-10-21，w2-final 收口；由人审 #198 触发）
- 背景：`w2-final` 全量复审抓到两件不是"代码写错"而是**"看起来完成、实际未验证"**的事：
  1. `composition.build_app()` 把 `MemoryRecall(..., embedder=FakeEmbedder(), enabled=True)` 当生产默认——
     本仓没有任何真 embedding 适配器（`litellm_adapter` 无 embed 路径、config 无 embedding 项），
     于是**向量通道在生产里永远不可能真工作**，而代码读起来像它在工作；
     更糟的是能力被拆成两个独立注入口（store 侧 `SQLiteMemoryStore(embedder=…)` 与 query 侧
     `MemoryRecall(embedder=…)`），组合根只注了后者：今天 store 侧为 None → 所有行 `embedding IS NULL`
     → 向量后端扫不到行 → 通道空转（**评审原话"假向量挤掉正确结果"在当前接线并不成立，实测机理不同**）；
     但任何一方单独接真实现时，query 与 stored 向量就来自不同空间，`recall.select` 按
     `-result.score` 排序 → 噪声直接决定注入哪 5 条，且没有任何测试会红。
  2. 文档反复出现"**新表对、旧处错**"（同一缺陷类人审已抓 14 次）：§17.1 记 BLK-10"已接线"，
     §7.2/§17 旧句仍写"生产端 0 调用/未接线"。既有四类机守（计数/引用/成对/否决）**结构上拓不到它**——
     它不是数字错，是同一事实在两处的状态相反。
- 决策：
  1. **向量能力收成单一接缝**：新 `providers/embedder_factory.py` 持判据（与 `provider_factory`/
     `model_windows` 同族，组合根守卫不许业务分支所以判据住 providers）：
     `EMBEDDER_BUILDERS` 数据表**当前为空**；`embedder_from_env()` 读 `QUESTOR_EMBED_MODEL`，
     未设 → `None`；设了但没有实现 → **出声 warning + `None`**，绝不退回 fake。
  2. **同一个实例喂两侧**：`AssembleSpec.embedder` 是唯一入口，组合根先解析 embedder 再构造 store，
     并把同一对象交给 store 与 recall；`shared_embedder(store, embedder)` 在两侧不是同一实例时
     **关掉 query 侧向量通道并 warning**（"半接"比不接危险）。
  3. **能力开关可观测**：`MemoryRecall.vector_channel_enabled` 只读属性——"召回开了"不等于
     "向量在跑"，让 `--context`/日志/测试能说真话。生产默认现为 **keyword + structured 开、向量关**。
  4. **fake 的正当位置是测试**：`providers/fake.py` 不删（它证向量通道接得通），但**只由调用方显式注入**
     （`spec.embedder=FakeEmbedder()` 或直接构造 `MemoryRecall`）。新判据
     `tests/unit/test_embedder_seam.py`（6 条）钉住：生产无替身、两侧同实例、不同实例即关、
     关向量与"无向量能力"结果逐字相同、env 设了没实现要出声。
  5. **组合根不得 import 测试替身**：`check_extension_points.py` 新增检查（`TEST_DOUBLE_MODULES`），
     `--self-test` 加"注 fake → 判红 / 注 providers 工厂 → 绿"两例。
     刻意**只管组合根**：`provider_factory` 用 `EchoProvider` 兜底是已核计的离线 fail-safe，
     与"声明一条不存在的通道"不是同一类问题——差别必须写下来，否则下一次会被"顺手全禁"。
  6. **文档守卫第五类检查（状态一致性）**：`STATE_TOPICS` 台账（主题 → 提及词 / 已完成措辞 /
     未完成措辞），规则三条：主题消失即红（防检查被静默废弃）；一旦有句子声称完成，就不允许
     再有句子声称未完成；带显式勘误标记（`已作废|已改|状态以|以 §17|见 §17.1|历史记录|原写`）的
     **句子**豁免（保留勘误记录是正当的）。
     **判定粒度必须是句**：行级实现在真文档上直接漏判——§17 整节写在一行里，同一行的"已改"
     会把陈旧状态句豁免掉（这条是实测，不是猜测）。`--self-test` 三例：植入矛盾→红、标勘误→绿、
     主题消失→红。
  7. **顺带修掉两个"平台性失明"**：
     `test_memory_disciplines` 的符号链接判据改为**注入 `os.path.islink`** 真跑两条分支
     （根是链接 / 中间目录是链接）并加反证，不再依赖主机特权 → 全量 skip 数回到基线 6；
     `tests/unit/test_recall_wiring.py` 里"生产 recall 带 embedder"的断言按事实改为
     `embedder is None` + `vector_channel_enabled is False`（该断言是同一 PR 内 4 个 commit 前
     我自己写的决定，本轮由评审推翻，见 §7 后果）。
  8. **补 §0.9 闭环验收 E1–E8**：`tests/e2e/test_closed_loop.py` 八条各一测试函数（E1 一 turn →
     SSE 帧含 `turn_completed` → **换新 store 实例读同一 db** 转录逐条相等；E2 两端同 session 并发
     入队按序不丢不重 + 同键幂等；E3 非 idle 提交事实化 + 重启后 `rebuild_run` 一致；E4 记住 →
     新 session 召回带条目级 `memory_injected` + citation 展开到 `path:line` + 消费只来自引用/真读；
     E5 撤回后不再召回、事件可回放、仍无 `memory_history` 表；E6 提醒到点 → `source='scheduler'`
     入 submissions → 前端读得到，且"今天别再提"/配额闸生效；E7 长会话压缩：条目数下降 +
     `verify_recovery_anchors` 读回原文 + 头部无孤儿；E8 六指标出数且成本停在 token/UNVERIFIED）。
     过程教训值得记：**三条判据最初按"想当然的契约"写就判红**——`memory_injected`/`memory_consumed`
     是 live-only（不在 `replay` 里）、idle 首条不发 `user_message`（B1 口径）。闭环用例必须读真契约。
- 后果：
  - 正面：生产不再声称一条不存在的通道；接真 embedding 只需登记 `EMBEDDER_BUILDERS`（组合根与
    调用方一行不改）；"半接"被机制挡住而非靠自觉；文档状态矛盾从此有第五类机守；闭环从"逐刀单测
    的集合"变成有一条端到端证据链；平台性 skip 少一个。
  - 代价：本轮**改写了 PR 内自己先前写的一条断言**（第 7 点第二条）——这是对同 PR 内一个决定的推翻，
    不是对历史基线断言的改写；`check_doc_cross_refs` 的 15 条 EXPECTED 与 e2e 桶需随每次收口更新；
    台账主题需人工维护（新增主题前先确认两侧措辞是固定说法，否则就是假阳机器）。
  - 需持续守：任何"默认开启的能力"必须有实现来源（判据是**代码里能不能真的走到那条路径**，不是
    名字像不像）；新体验面/新通道一律先问"是不是又开了第二通道"；正文写状态必须引 §17.1 条目号
    或显式标勘误，不允许裸状态词。
- 备选（被否）：
  1. **保留 FakeEmbedder 当生产默认，只在文档加一句"其实没效果"**：否——正是"新表对、旧处错"的
     源头，且掩盖了两侧注入点会分叉的真缺陷。
  2. **把 `EchoProvider` 一并禁掉（全仓不许出现 fake）**：否——它是已核计的离线兜底 provider，
     与虚假能力声明不同类；一刀切会逼出"为了过守卫再造一层包装"的坏代码。
  3. **状态一致性用相似度/词义模糊匹配**：否——假阳机器会让人开始忽略守卫输出；改成主题台账 +
     固定措辞 + 句级判定，红必须可解释。
  4. **符号链接用例改成"标记 skip 为已覆盖"**：否——改成注入判定，任何主机都真跑那两条分支。
  5. **E1–E8 用"路径存在/接口有测试"来声称闭环**：否——§0.9 明确禁止；每条都要端到端可复跑。
- 关联：`ADR-0055`（召回默认开 + 命中≠消费；本 ADR 收窄其 embedder 口径）、`ADR-0026`（向量后端
  可缺省降级）、`ADR-0058`（噪声率口径依赖条目级消费）、`ADR-0059`（不开第二通道）；
  v3 §6.2/§17.1/§21 G2/G11。
  代码：`providers/embedder_factory.py`、`composition.py`、`memory/recall.py`、
  `scripts/check_extension_points.py`、`scripts/check_doc_cross_refs.py`、
  `tests/unit/test_embedder_seam.py`、`tests/unit/test_recall_wiring.py`、
  `tests/unit/test_memory_disciplines.py`、`tests/e2e/test_closed_loop.py`、`pyproject.toml`（e2e 标记）。
