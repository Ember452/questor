# Appearance Packages

外观四包是**叶子**：任何层都可以读它们，它们只依赖 `platform`，不持有业务状态， 也不 import 引擎或运行时。
`layers` 契约故意不含这四个包，所以它们的边界由两处机械守住：`check_layout` 的 R6（每包一份地图）
与 `check_agents_docs` 的 C1/C2。

`vim/` 包已于 2026-10-25 删除（仓内零引用；`/vim` 命令只读写 `settings.vim_mode` /
`app_state.vim_enabled`，不经过该包）。开关保留以兼容已持久化的配置；REPL 当前是行式输入，
没有行编辑器，所以开关**不产生编辑行为**——接入行编辑器或删除命令需单独立项。

| 包 | 职责 | 被谁读 |
| --- | --- | --- |
| `src/questorharness/state` | 应用状态容器与只读快照视图 | `bootstrap`、`commands` |
| `src/questorharness/keybindings` | 键位表与用户覆盖解析 | `bootstrap`、`surfaces` |
| `src/questorharness/themes` | 主题定义与调色板解析 | `bootstrap`、`commands` |
| `src/questorharness/output_styles` | 输出样式目录与选择 | `bootstrap`、`commands` |

新增外观包时必须同 PR 建一份包级 `AGENTS.md`（C1 会要求），并把包名加进
`scripts/guards/check_agents_docs.py` 的 `PACKAGE_MAPS`。
