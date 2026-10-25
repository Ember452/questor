/** 页面 props：所有页面只拿 wire 运行时与视图状态，不碰引擎内部。 */

import type { WireRuntime } from "../shared/transport/wireRuntime";
import type { ViewState } from "../app/viewModel";

export interface PageProps {
  runtime: WireRuntime;
  view: ViewState;
  onSend: (line: string) => void;
  onCancel: () => void;
  onApprove: (id: string, approved: boolean) => void;
  onAsk: (id: string, answer: string) => void;
}
