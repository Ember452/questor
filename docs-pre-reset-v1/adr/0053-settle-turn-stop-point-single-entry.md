# ADR-0053: settle_turn 收口到 Stop 点位——兼容参数是薄糖，不是第二套机制

- 状态：✅（2026-10-21，B5/c3）
- 背景：B6 把 `settle_turn` 直接挂在 `DefaultTurnLoop(settle=...)` 上；B5 新增 13 个具名点位后，
  §5.1 第 13 行 `Stop` 必须成为 turn 定稿/记忆写回的唯一生产者。既有测试
  `tests/integration/test_settle_turn.py` 直接传 `settle=settler.settle`，R3 禁止改既有断言；
  若同时保留“直连字段 + Stop 链”就是两套机制并存，违反单一入口。
- 决策：
  1. **内核只持一个字段** `self._stop: ObserveChain`；`_settle_turn` 只有一次
     `await self._stop.emit(boundary)` 调用点。
  2. `settle=` 关键字保留为 **R3 兼容薄糖**：构造时包成**单条** `ExtensionDescriptor(id="settle-turn",
     kind=OBSERVE, at="Stop", priority=100)` 的 `ObserveEntry`；不存在第二个 `self.settle` 字段，
     也没有第二条执行路径。
  3. surface 侧由 `CliSurface.build_extension_registry()` 把 `TurnSettler` 注册为 Stop OBSERVE 条目，
     `_loop` 解析出 `ObserveChain` 后以 `stop=` 注入；CLI/serve/serve-openai/sidecar 四个入口共用
     同一形状。
  4. OBSERVE 链的失败语义固定为 `FAILED_CONTINUE`：条目抛异常或返回 `FAILED_ABORT` 都被归一，
     turn 绝不因记忆写失败而失败（§6.4b）。
- 后果：
  - 正面：settle 的唯一入口 = Stop 点位；`inspect-extensions` 能看到 `settle-turn`；内核不 import
    `policy.registry`，仍只依赖 contracts。
  - 代价：`settle=` 关键字继续存在于构造签名（仅为兼容），新代码应传 `stop=`；ADR 记录这一例外，
    避免被误读为“两套路径”。
  - 需持续守：`_settle_turn` 内不得再出现第二个直调分支；守卫
    `scripts/check_extension_points.py` 检查 kernel 不 import registry、组合根无业务分支。
- 备选（被否）：
  1. **删除 `settle=` 并改既有测试**：否——R3 明确禁止改既有断言；改测试是用户授权项。
  2. **保留 `self.settle` 字段并在 `_settle_turn` 里 `if self.settle` 优先**：否——两套路径并存，
     正是本刀要消除的形状。
  3. **把 `TurnSettler` 移进 contracts**：否——它做 IO（store/bus）与写回判定，属 L2/L6 装配，
     L0 只放声明与纯链。
- 关联：v3 §5.1（Stop 行）/§5.2（descriptor 6 字段）/§6.4b（settle 三判据）；
  `contracts/extension.py`、`policy/registry.py`、`kernel/loop.py`、`kernel/settle.py`、
  `surfaces/cli.py`；`tests/unit/test_stop_point.py`、`tests/integration/test_settle_turn.py`。
