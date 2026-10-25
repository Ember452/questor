# Questor Desktop（Electron 壳）

- 引擎：`python -m questorharness --studio-host`（stdout 首行握手，stdin 父租约）。
- 界面：`apps/web` 的 web 构建产物（阶段 5 起由壳内 loadURL 指向回环宿主）。
- 打包：PyInstaller **onedir**（`packaging/questor-engine.spec`）+ electron-builder NSIS。
- 更新：`versions/<ver>/` + `current.json`，启动失败自动回滚（`electron/updater.cjs`）。

## 本地

```powershell
node apps/desktop/scripts/build-engine.mjs   # 需要 pyinstaller
npm --prefix apps/desktop run check
npm --prefix apps/desktop test               # 更新器回滚矩阵
```

## 红线

- 不原地覆盖旧版本；回滚只切指针。
- 握手必须校验 `port` 与 `token>=32`，失败即拒绝加载。
- `stdin` 只在退出时关闭；引擎崩溃最多重启 3 次。
