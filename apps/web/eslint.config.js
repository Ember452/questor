import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["dist", "src/generated", "src-tauri/target", "src-tauri/gen"],
  },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
    },
  },
  // 叶子互不引用（千文件演进的机械红线）：pages 之间、卡片之间不得横向 import，
  // 共享逻辑下沉 shared/，组合只发生在 pages 注册表与 cardSlots。与禁 WebSocket
  // 同级——组件网一旦横向连边，规模上来就是不可测的耦合网。
  {
    files: ["src/pages/**/*.tsx", "src/pages/**/*.ts"],
    // registry 是唯一组合点（它的职责就是 import 页面）；测试文件不受此限。
    ignores: ["src/pages/registry.ts", "**/*.test.*"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["./*", "!./types"],
              message:
                "pages 之间禁止互相引用：共享逻辑下沉 src/shared/，页面经 registry.ts 组合。",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["src/shared/ui-kit/cards/**/*.tsx", "src/shared/ui-kit/cards/**/*.ts"],
    ignores: ["**/*.test.*"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["./*", "!./cards.module.css"],
              message:
                "卡片之间禁止互相引用：共享 UI 下沉 src/shared/ui-kit/，分发只在 cardSlots。",
            },
          ],
        },
      ],
    },
  },
);
