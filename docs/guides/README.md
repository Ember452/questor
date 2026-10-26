# 使用指南

面向"我想做一件事"的文档。想先懂原理去 [内部原理](../internals/README.md)，
想查参数去 [参考手册](../reference/README.md)。

| 我想… | 看这篇 |
| --- | --- |
| 从零装好并跑通第一次对话 | [快速开始](quickstart.md) |
| 在 Windows 上装、换网络环境、离线准备 | [安装](install.md) |
| 打开桌面应用（Electron 壳 + Web 界面） | [桌面版指南](desktop.md) |
| 跑不起来 / 报错 / 中文乱码 | [故障排查](troubleshooting.md) |
| 跑测试、看懂测试分层 | [测试指南](testing.md) |

## 三句话版本

```powershell
uv sync
uv run python -m questor init
uv run python -m questor
```

细节与前置条件在 [快速开始](quickstart.md)。
