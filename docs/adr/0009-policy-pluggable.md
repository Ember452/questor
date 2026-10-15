# ADR-0009: 策略可插拔机制

- 状态：✅（2026-10-15）
- 背景：L4 策略是唯一高频迭代区（不断加算法/调提示词），必须与 L2 内核解耦，且要能灰度/回滚。实扒 MetaGPT/DeepCode/hermes 三家高度收敛（见 `docs/references/R05-policy-pluggable.md`）。
- 决策：
  1. **热替换 = run 内快照冻结、换=新 run**：创建 run 时解析一次、按值快照 `policy_id+fingerprint`，整 run 用同一份；严禁活 run 中途 swap。
  2. **A/B 按 fingerprint 路由**（内容指纹，非版本号）；`run_started` 事件带 `policy_ref{id,fingerprint}`（只增字段）。
  3. **进程内默认 + 远程只预留**：view/intent 纯 frozen 数据即可，v1 不引入 RPC/序列化传输（C12）。
  4. 注册表错误二分（Unknown vs Broken）、降级 fail-open（回落默认+WARN，绝不让 run 起不来）。
- 后果：换/灰度/AB 策略不动内核；代价=活 run 不能中途换策略（本就该如此）。接口下沉 `contracts/policy.py`、机制在 `design/05-policy.md`。
- 备选(被否)：允许活 run 热 swap（撕裂状态/回放）→ 否；现在就为远程策略序列化一切（过度设计）→ 否。
- 关联：`design/05-policy.md`、`design/04-turn-loop.md §9`、C12。
