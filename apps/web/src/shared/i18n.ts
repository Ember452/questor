/** i18n 骨架：中文源文即 key（Reasonix 模式），英文表后补、缺译回落中文。
 *
 * 接入节奏：五张对话卡 + 页面徽标为首批；新增文案一律走 `t()`，
 * 旧字面量随触碰迁移——不做一次性全仓 sweep。
 */

const EN: Readonly<Record<string, string>> = {
  // 首批（卡片与徽标）；英文翻译就位前回落中文原文。
};

export function t(key: string): string {
  return EN[key] ?? key;
}
