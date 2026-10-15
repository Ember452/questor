## 这个 PR 改了什么

<!-- 简明描述 -->

## 关联

<!-- 关联 issue：Fixes # / Refs # ；触及分层/契约/难回退决策是否已记 docs/adr/* ？ -->

## DoD 自检（勾全再提）

- [ ] `uv run ruff check .` 通过
- [ ] `uv run pytest` 通过
- [ ] 冷导入通过（改了包/依赖时）
- [ ] 不违反 `docs/design/HARD-CONSTRAINTS.md`（单写者/只读视图/事件分层/权限/沙箱降级/接缝冻结）
- [ ] 触及分层或契约 → 已同步更新 `docs/design/*`，必要时加/改 ADR
- [ ] 新增/改动测试覆盖本改动

## 备注 / 截图
