# 新增一个页面（四步）

1. `apps/web/src/pages/registry.ts` 加一条 `{id, capability, title, component}`。
2. 当前 profile 的 `ui.capabilities` 加同名 key：初始 `declared`（入口不出现），实现完改 `ready`
   （`src/questor/profiles/coding.yaml` 或 `personal.yaml`）。
3. 若消费新 kind：`protocol/app-wire.schema.json` 加 kind（只加不改）→ 两侧重新生成 →
   `apps/web/src/app/cardSlots.ts` 补槽位（`Record` 穷尽会强制）。
4. `docs/plan/mapping/questor-coding.md`（或 `questor-personal.md`）加一行。

约束：page id 一入 git 即契约——**只增不改名、不删除**；下线/替换用 `absent` 并在映射表登记。
导航、命令面板、快捷键全部从 `registry` 派生，禁止硬编码路由。
