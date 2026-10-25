/** 页面注册表：导航 / 命令面板 / 快捷键都从这里派生，禁止硬编码路由。 */

import type { ComponentType } from "react";

import { ChatPage } from "./ChatPage";
import { ThreadPage } from "./ThreadPage";
import type { PageProps } from "./types";

export interface PageDef {
  id: string;
  capability: string;
  title: string;
  component: ComponentType<PageProps>;
}

export const PAGES: PageDef[] = [
  { id: "chat", capability: "chat", title: "对话", component: ChatPage },
  { id: "thread", capability: "thread", title: "会话快照", component: ThreadPage },
];
