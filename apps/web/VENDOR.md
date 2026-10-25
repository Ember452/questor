# apps/web — vendored 归属与基线

`apps/web` 是 DeepCode `desktop/` 的 vendored 副本（MIT），只允许存在于 `apps/` 下；
`src/` 内的 CONVENTIONS §4.5 不适用于这里，但 `apps/web/VENDOR.md` 是硬约束。

基线: a6303ff4ec4425bce7efda36fd940480b0f85d73

## 禁区

- `src/styles/tokens.css`

## 已改

- `.gitignore` — 新增（忽略 `.dev-server.json` 运行时产物）
- `package.json` — scripts 改为 owned；新增 `@tanstack/react-virtual`
- `package-lock.json` — 新增 owned 依赖后的锁文件
- `vite.config.ts` — version 读取改为常量；web 输出目录改为 `dist`
- `index.html` — 标题改 Questor；入口改 `webMain.tsx`
- `src/App.module.css` — 重写为 4a 临时外壳样式
- `src/App.tsx` — 重写为 wire-native 壳
- `src/webMain.tsx` — 改指向新 App
- `playwright.config.ts` — 改为 globalSetup（真宿主 + preview）与截图基线目录

## 已裁

- `src/features/**`
- `src/shared/ui-kit/**`
- `src/shared/transport/**`
- `src/shared/confirmAction.ts`
- `src/generated/app-server.ts`
- `src/platform/**`
- `src/components/**`
- `src/rpc/**`
- `src/app/**`
- `src/desktopMain.tsx`
- `src/main.tsx`
- `src/BrowserShell.tsx`
- `src/webShell.module.css`
- `src/App.test.tsx`
- `src/styles/tokens.test.ts`

## 已裁

- e2e/web.spec.ts

## 新增

- `VENDOR.md`
- `LICENSE.deepcode`
- `src/generated/app-wire.ts`
- `src/generated/wire-fixtures.json`
- `src/shared/transport/wireRuntime.ts`
- `src/shared/transport/wireTypes.ts`
- `src/shared/ui-kit/ErrorBoundary.tsx`
- `src/shared/ui-kit/cards/**`
- `src/app/App.tsx`
- `src/app/viewModel.ts`
- `src/app/viewModel.test.ts`
- `src/app/cardSlots.ts`
- `scripts/gen-web-fixtures.mjs`
- `scripts/**`
- `src/pages/**`
- `src/shared/theme/**`
- `docs/**`
- `e2e/**`

---

## 基线偏差（已并入 C1，守卫不追踪）

- `vite.config.ts`：上游从 `../core/version.py` 读版本；本仓无该布局，改为常量 `0.1.0`。
- 未复制 `src-tauri/**`、`src/rpc/tauriRuntime.ts`、`src/rpc/tauriRuntime.test.ts`、
  `src/platform/confirmAction.test.ts`（Tauri/对话框绑定；Web 形态不使用）。
- 未复制 `sidecar-requirements.*`（Python 侧由本仓 PyInstaller onedir 取代）。
- `src-tauri` 依赖暂保留在 `package.json`（首刀零改动原则）；4a 剪枝后按需清理。

## 归属

| 目录 | 归属 | 说明 |
|---|---|---|
| `src/styles/**` | vendored | DeepCode token/CSS Module 体系 |
| `src/shared/**`（改名后） | vendored → owned | 4a 起逐文件迁移为 owned |
| `src/generated/app-wire.ts` | owned（生成物） | 由 `scripts/codegen/gen_wire_ts.mjs` 生成 |
| `src/app/**`、`src/features/**` | 4a 剪枝后 owned | RPC 控制器删除，新 shell 由本仓编写 |
