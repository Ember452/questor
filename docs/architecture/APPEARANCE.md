# Appearance Packages

外观四包是**叶子**：任何层都可以读它们，它们只依赖 `platform`，不持有业务状态， 也不 import 引擎或运行时。
`layers` 契约故意不含这四个包，所以它们的边界由两处机械守住：`check_layout` 的 R6（每包一份地图）
与 `check_agents_docs` 的 C1/C2。

`vim/` 包、`/vim` 命令、`vim_mode` 设置与 `vim_enabled` 状态已于 2026-10-25 一并删除：
它们声明了“vim 模式”，但 REPL 是行式输入、没有行编辑器，开关不产生任何行为——
“声明与行为不一致”按缺陷处理。将来的 vim 键位属于编辑器/前端实现（Studio 编辑器自持 keymap），
不回到引擎设置层。

| 包 | 职责 | 被谁读 |
| --- | --- | --- |
| `src/questorharness/state` | 应用状态容器与只读快照视图 | `bootstrap`、`commands` |
| `src/questorharness/keybindings` | 键位表与用户覆盖解析 | `bootstrap`、`surfaces` |
| `src/questorharness/themes` | 主题定义与调色板解析 | `bootstrap`、`commands` |
| `src/questorharness/output_styles` | 输出样式目录与选择 | `bootstrap`、`commands` |

新增外观包时必须同 PR 建一份包级 `AGENTS.md`（C1 会要求），并把包名加进
`scripts/guards/check_agents_docs.py` 的 `PACKAGE_MAPS`。
