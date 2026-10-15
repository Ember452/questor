# SECURITY.md

Questor 是一个能读写本地文件、执行命令、调用外部服务的桌面 Agent，我们把安全放在第一位。

## 报告一个漏洞

**请不要开公开 Issue 报告安全问题。** 请通过 GitHub 私密安全通告报告：

- 打开：**Security → Report a vulnerability**
- 地址：https://github.com/Ember452/questor/security/advisories/new

我们会在收到后尽快确认。请附上复现步骤与影响范围。

## 支持版本

| 版本 | 支持 |
|---|---|
| pre-alpha（当前） | 尽力而为 |
| ≥ v1.0 | 安全补丁 |

## 范围提示（我们尤其在意）

- 权限绕过：`deny` / 敏感路径 denylist（如 `~/.questor/.env`、凭据）被越过。
- 沙箱逃逸 / 命令注入（shell 解析、MCP 远程工具）。
- 凭据泄露：日志/错误/事件载荷中泄漏 API key/token。

## 致谢

对经确认的安全问题，我们愿在修复后致谢（如你同意）。
