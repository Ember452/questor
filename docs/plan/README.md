# 施工计划与映射

这一层记录**怎么做完的**，不是"它怎么运转"（那在 [内部原理](../internals/README.md)）。
计划文件带验收台账，改计划前先读台账末尾，避免重复踩已关闭的坑。

| 文件 | 内容 |
| --- | --- |
| [01 结构加固](01-structure-hardening.md) | 分层、目录预算、守卫体系与验收台账 |
| [02 Studio serve 宿主](02-studio-serve-host.md) | 回环宿主与线协议 |
| [03 终端 REPL](03-terminal-repl.md) | 行式 REPL 与全屏 TUI 的落地路径 |
| [04 personal 就绪](04-personal-readiness.md) | 主动运行时、检索降级链与三个 runtime 位的消费方落地 |

## 形态映射

把"产品要什么"对到"引擎给什么"的三张对照表：

| 文件 | 对照对象 |
| --- | --- |
| [questor-personal](mapping/questor-personal.md) | 个人 Agent 形态 |
| [questor-coding](mapping/questor-coding.md) | 编码 Agent 形态 |
| [terminal-coding](mapping/terminal-coding.md) | 终端形态 |

新增计划文件时，请同时在上面两张表里加一行——未登记的文档会被可达性守卫判红。
