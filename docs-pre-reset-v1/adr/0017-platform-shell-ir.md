# ADR-0017: Shell 工具采用 dialect 化 IR，Windows 一等支持 PowerShell

- 状态：✅（2026-10-15）
- 背景：原 P2 计划把 `bash` 与 POSIX 解析语料直接当作 Windows DoD；但目标开发机 PATH 中存在 `powershell.exe`、没有 `bash`，而 `wsl.exe` 的路径、进程树和沙箱语义又与 Windows host 不同。只用一个 POSIX parser 会把未识别的 PowerShell 语义错误地当作普通 token。
- 决策：
  - 两个一等工具：`bash`（POSIX shell）与 `powershell`（Windows PowerShell/pwsh）。两者共享 `ShellAnalysis` IR，不共享错误的语法假设。
  - ToolRegistry 按真实绝对路径与可执行探测注册；缺 `bash` 时该工具不可用，不静默改跑 cmd、PowerShell 或 WSL。
  - PowerShell parser 至少处理：分号/管道/`&`、单双引号、反引号转义、重定向、常见 alias（`rm/del/rmdir/ri/rd/ls/dir/cat/gc`）、参数拆分、子程序、动态执行、encoded command、变量作为程序名。
  - 不能证明 read-only 的命令必须走 ask；`Invoke-Expression`、scriptblock、external program、动态路径和未识别 cmdlet 永远不能自动 allow。
  - Windows P2 DoD 用 PowerShell 的等价危险命令复现；POSIX DoD 在具备 bash 的 Linux/macOS/CI 复现。两者都是主验收面，不允许用 fake 替代真实本机复现。
- 后果：Windows 用户获得真实可审批的 shell 能力，解析安全语义不再跨平台冒充；代价是 P2 需要两套 parser 与两套命令绕过语料。
- 备选（被否）：
  1. 只实现 `bash`，Windows 跳过 DoD：与项目 Windows 主开发环境矛盾 → 否。
  2. 用 WSL 透明执行：文件权限、路径、进程树和 sandbox backend 均不一致 → 否。
  3. 用 cmd.exe：引号、命令替换与权限语义更弱，不能提供可靠审批摘要 → 否。
- 关联：ADR-0015、ADR-0018；[`../design/03-tool-interface.md`](../design/03-tool-interface.md) §6/§11；[`../plan-archive/02-p2-tools-permission.md`](../plan-archive/02-p2-tools-permission.md)。
