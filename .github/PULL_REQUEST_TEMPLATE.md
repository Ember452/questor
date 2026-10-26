## 这个 PR 改了什么

<!-- 简明描述；涉及行为变更请写清前后差异 -->

## 关联

<!-- 关联 issue：Fixes # / Refs #；触及分层、契约或难回退决策时，是否已记 docs/adr/ ？ -->

## DoD 自检（勾全都再提）

- [ ] `uv run ruff check .` 通过
- [ ] `uv run pytest` 通过
- [ ] 冷导入通过（改了包或依赖时）
- [ ] 不违反 [docs/CONVENTIONS.md](../docs/CONVENTIONS.md) 的行为守则与分层红线（单写者 / 只读视图 / 事件不反哺 / 权限 / 沙箱降级）
- [ ] 涉及分层或契约 → 已同步更新 [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) 或 [docs/architecture/](../docs/architecture/README.md)，必要时加/改 ADR
- [ ] 涉及权限、沙箱、凭据 → 已说明失败语义（fail-closed 还是降级）
- [ ] 新增/改动测试覆盖本改动
- [ ] 改了文档 → `uv run python scripts/check.py` 的文档守卫通过（死链会变红）

## 备注 / 截图

<!-- 界面改动请附截图；无法附带时说明验证方式 -->
