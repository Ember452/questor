# apps/web — vendored 归属与基线

`apps/web` 是既有授权骨架的 vendored 副本（授权与谱系由所有者持有，不入库），
只允许存在于 `apps/` 下；
`src/` 内的 CONVENTIONS §4.5 不适用于这里，但 `apps/web/VENDOR.md` 是硬约束。

基线: a6303ff4ec4425bce7efda36fd940480b0f85d73

## 禁区

- `src/styles/tokens.css`

## 已改

- `eslint.config.js` — 新增叶子互不引用红线（pages/cards 横向 import 即红，registry 豁免）
- `e2e/global-setup.ts` / `e2e/global-teardown.ts` — 接入 stub llm 装配
- `src/shared/ui-kit/cards/*.tsx` — 文案走 `t()`
- `src/pages/ChatPage.tsx` — 徽标文案走 `t()` + render 穷尽守卫
- `src/shared/theme/**`（token 底座改名与别名注释；内容语义未动）
- `.gitignore` — 新增（忽略 `.dev-server.json` 运行时产物）
- `package.json` — scripts 改为 owned；新增 `@tanstack/react-virtual`；移除未引用的 tauri 全家（ADR-0005/0007 判 Electron）
- `package-lock.json` — 新增 owned 依赖后的锁文件
- `vite.config.ts` — version 读取改为常量；web 输出目录改为 `dist`
- `index.html` — 标题改 Questor；入口改 `webMain.tsx`
- `src/App.module.css` — 重写为 4a 临时外壳样式
- `src/App.tsx` — 重写为 wire-native 壳
- `src/webMain.tsx` — 改指向新 App
- `playwright.config.ts` — 改为 globalSetup（真宿主 + preview）与截图基线目录

## 已裁

- `LICENSE*`（上游许可文件不入本仓）
- `e2e/web.spec.ts`（上游 e2e，被本仓 spec 取代）
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

## 新增

（owned 文件；对基线而言是新增而非裁剪）

- `VENDOR.md`
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
- `src/shared/i18n.ts`
- `src/shared/i18n.test.ts`
- `src/shared/theme/**`
- `docs/**`
- `e2e/**`

---

## 基线偏差（已并入 C1，守卫不追踪）

- `vite.config.ts`：上游从 `../core/version.py` 读版本；本仓无该布局，改为常量 `0.1.0`。
- 未复制 `src-tauri/**`、`src/rpc/tauriRuntime.ts`、`src/rpc/tauriRuntime.test.ts`、
  `src/platform/confirmAction.test.ts`（Tauri/对话框绑定；Web 形态不使用）。
- 未复制 `sidecar-requirements.*`（Python 侧由本仓 PyInstaller onedir 取代）。
- ~~`src-tauri` 依赖暂保留~~（已清理：零引用即移除，见 已改/package.json）。

## 归属

| 目录 | 归属 | 说明 |
|---|---|---|
| `src/styles/**` | vendored | 上游骨架 token/CSS Module 体系 |
| `src/shared/**`（改名后） | vendored → owned | 4a 起逐文件迁移为 owned |
| `src/generated/app-wire.ts` | owned（生成物） | 由 `scripts/codegen/gen_wire_ts.mjs` 生成 |
| `src/app/**`、`src/features/**` | 4a 剪枝后 owned | RPC 控制器删除，新 shell 由本仓编写 |
