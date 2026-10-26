# 故障排查

排查顺序：先 `doctor`，再 `--dry-run`，最后看日志。大部分"跑不起来"属于环境问题，
不是引擎问题。

## 先收集这三样

```powershell
uv run python -m questor doctor          # 工作区与凭据自检
uv run python -m questorharness --dry-run  # 解析后的运行配置、技能、命令、工具（不调模型）
```

日志在 `~/.questorharness/logs/`（可用 `QUESTORHARNESS_LOGS_DIR` 改位置）。
调日志级别：`$env:QUESTORHARNESS_LOG_LEVEL = "DEBUG"`，或引擎加 `--debug`。

## 常见问题

### 启动后没有真正调用模型

没有可用凭据时，引擎会回落到 **echo 演示 provider**——它只回显请求，不是真模型。
用 `--dry-run` 看当前解析到的 `provider` / `model`，或 `doctor` 看凭据状态。

### 中文或框线显示成乱码

Windows 控制台默认代码页不是 UTF-8，而 CLI 输出含中文与框线字符。

```powershell
chcp 65001
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
```

把输出重定向到文件再读时，同样按 UTF-8 解码（`Get-Content -Encoding UTF8`），
否则看到的是"UTF-8 字节被当 GBK 解码"的乱码。

### TUI 启动不了 / 变成一行一个提示符

全屏 TUI 需要真正的终端。stdin 或 stdout 不是 TTY（管道、重定向、CI、某些 IDE 终端）时，
引擎会自动降级为行式 REPL；也可以显式加 `--plain`。

### `uv sync` 很慢或超时

`pyproject.toml` 把阿里云镜像声明为默认索引。国内网络通常更快；境外网络反而会拖慢，
删掉该节的 `default = true` 后重试即可（详见 [安装](install.md)）。

### `make` 找不到

Windows 上不一定有 `make`。用等价入口：

```powershell
uv run python scripts/check.py          # 全量门禁
uv run python scripts/check.py --fast   # 快速档
```

### 文档守卫报 `missing link target`

文档里的相对链接或反引号路径指向了不存在的文件。修链接是首选；确实要短期保留的
历史坏链，只能在**文件头 30 行内**用 `<!-- known-stale-refs: <路径> -->` 逐条登记。
链接修好后必须把登记项删掉，否则守卫会报"登记项已不再匹配"。

### 桌面壳白屏或一闪就退

见 [桌面版指南](desktop.md) 的排障小节：渲染层构建产物与握手是两大高频原因。

### 端口被占用 / 连不上回环宿主

引擎与壳之间用随机回环端口 + 一次性令牌。若壳报握手失败，先确认没有残留的
`questorharness` 进程占用；关闭后重试。

## 提 issue 之前

1. 附上 `doctor` 与 `--dry-run` 的输出；
2. 附上出错时的日志片段（**先脱敏**：删除 API key、token、私有路径、会话内容）；
3. 说明平台（Windows 版本 / Linux 发行版）、Python 与 uv 版本。

安全问题不要开公开 issue，走 [SECURITY.md](../../SECURITY.md) 的私密通告。
