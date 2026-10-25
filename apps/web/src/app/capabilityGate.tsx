/** capability 三态门控：ready 渲染；declared/absent 入口不出现。 */

import type { ReactNode } from "react";

import type { PageDef } from "../pages/registry";

export type CapabilityState = "ready" | "declared" | "absent";

export function isVisible(page: PageDef, capabilities: Record<string, CapabilityState>): boolean {
  return capabilities[page.capability] === "ready";
}

export function gate(
  page: PageDef,
  capabilities: Record<string, CapabilityState>,
  render: () => ReactNode,
): ReactNode | null {
  return isVisible(page, capabilities) ? render() : null;
}
