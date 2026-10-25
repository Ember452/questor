# apps/web — vendored 归属与基线

`apps/web` 是 DeepCode `desktop/` 的 vendored 副本（MIT），只允许存在于 `apps/` 下；
`src/` 内的 CONVENTIONS §4.5 不适用于这里，但 `apps/web/VENDOR.md` 是硬约束。

基线: a6303ff4ec4425bce7efda36fd940480b0f85d73

## 禁区

- `src/generated/**`
- `package-lock.json`

## 已改

- `package.json` — scripts 改为 owned（lint/typecheck/test/build:web/check:protocol），删 tauri/sidecar 类脚本
- `vite.config.ts` — version 读取改为常量；web 输出目录改为 `dist`
- `index.html` — 标题改 Questor；入口改 `webMain.tsx`

## 已裁

- `src/desktopMain.tsx` — Tauri 桌面入口（Web 形态不适用）
- `src/main.tsx` — 指向 Tauri 入口，随之删除

## 新增

- `VENDOR.md` — 本文件（归属与基线）
- `LICENSE.deepcode` — 上游 MIT 原件
- （逐路径一行：`path — 归属 owned`）

---

## 基线偏差（已并入 C1，守卫不追踪）

- `vite.config.ts`：上游从 `../core/version.py` 读版本；本仓无该布局，改为常量 `0.1.0`。
- 未复制 `src-tauri/**`、`src/rpc/tauriRuntime.ts`、`src/rpc/tauriRuntime.test.ts`、
  `src/platform/confirmAction.test.ts`（Tauri/对话框绑定；Web 形态不使用）。
- 未复制 `sidecar-requirements.*`（Python 侧由本仓 PyInstaller onedir 取代）。
- `src-tauri` 相关依赖保留在 `package.json` 中不删（首刀零改动原则）；4a 接门后按需清理。

## 归属

| 目录 | 归属 | 说明 |
|---|---|---|
| `src/styles/**` | vendored | DeepCode token/CSS Module 体系 |
| `src/shared/**`（改名后） | vendored | 4a 起逐文件迁移为 owned |
| `src/generated/app-wire.ts` | owned（生成物） | 由 `scripts/codegen/gen_wire_ts.mjs` 生成 |
| `src/app/**`、`src/features/**` | 4a 剪枝后 owned | RPC 控制器删除，新 shell 由本仓编写 |
