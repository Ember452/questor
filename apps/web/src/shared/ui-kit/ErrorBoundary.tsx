/** 单卡错误隔离：一张卡 throw 只降级该卡，不白屏。 */

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  label?: string;
}

interface State {
  message: string | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { message: null };

  static getDerivedStateFromError(error: unknown): State {
    return { message: error instanceof Error ? error.message : String(error) };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("card crashed", this.props.label, error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.message !== null) {
      return (
        <div role="alert" data-testid="card-degraded" style={{ padding: 8, border: "1px solid #b45309" }}>
          这一条渲染失败（{this.props.label ?? "card"}）：{this.state.message}
        </div>
      );
    }
    return this.props.children;
  }
}
