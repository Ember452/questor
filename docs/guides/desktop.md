# 桌面版指南

桌面版是 **Electron 壳 + React 渲染层 + Python 引擎** 的三段结构，不是独立的第二套实现。

```text
apps/desktop  (Electron 主进程 / 预加载 / 更新器)
      |  启动子进程并握手
      v
python -m questorharness --studio-host     回环 HTTP 宿主 + 事件流
      ^
      |  加载构建产物
apps/web      (React 渲染层，也可单独在浏览器里跑)
```

## 启动顺序

1. 壳进程拉起 `python -m questorharness --studio-host`；
2. 引擎在 **stdout 首行**输出握手信息（回环端口 + 一次性令牌）；
3. 壳校验端口与令牌（令牌长度必须 ≥ 32），失败即拒绝加载；
4. 壳把渲染层指向回环地址，之后所有交互走 HTTP + 事件流；
5. 引擎崩溃时最多重启 3 次，`stdin` 只在退出时关闭（父租约）。

这条链路是**网络关系，不是 import 关系**：`apps/web` 与引擎之间没有 Python 依赖边，
分层阶梯不受影响。

## 从源码运行

需要 Node 24 与已完成的 Python 环境（见 [安装](install.md)）。

```powershell
npm --prefix apps/web run build:web      # 先构建渲染层（tsc --noEmit && vite build）
npm --prefix apps/desktop start          # 启动 Electron 壳
```

开发渲染层时可以只跑 Vite 开发服务器：

```powershell
npm --prefix apps/web run dev
```

引擎默认按内置目录查找前端产物；产物在别处时用 `QUESTOR_WEB_DIST` 指向目录：

```powershell
$env:QUESTOR_WEB_DIST = "D:\path\to\questor\apps\web\dist"
```

## 打包

```powershell
node apps/desktop/scripts/build-engine.mjs   # 引擎 sidecar，需要 pyinstaller（PyInstaller onedir）
npm --prefix apps/desktop run dist           # electron-builder，Windows NSIS
```

目前只产出 Windows 安装包；代码签名与自动更新尚未接入。

## 检查与自测

| 命令 | 作用 |
| --- | --- |
| `npm --prefix apps/desktop run check` | 主进程与预加载脚本语法检查 |
| `npm --prefix apps/desktop run test` | 更新器回滚矩阵（node:test） |
| `npm --prefix apps/desktop run smoke` | 引擎冒烟 |
| `npm --prefix apps/desktop run e2e` | Electron 端到端 |
| `npm --prefix apps/web run typecheck` | 渲染层类型检查 |
| `npm --prefix apps/web run test` | 渲染层单测（vitest） |

CI 的 `web` 作业覆盖渲染层；桌面构建在 `desktop.yml` 里，只在相关路径变更时触发。

## 排障

- **白屏**：渲染层没构建，或 `QUESTOR_WEB_DIST` 指向了错误目录。
- **壳启动即退出**：握手失败（端口非法或令牌过短），查看引擎 stderr 与 `~/.questorharness/logs/`。
- **打包后找不到引擎**：`build:engine.mjs` 未先执行，或 PyInstaller 不可用。
- 更多通用问题见 [故障排查](troubleshooting.md)。
