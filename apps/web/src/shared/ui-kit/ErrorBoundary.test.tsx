import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function Boom(): never {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  it("一张卡抛错只降级该卡，兄弟节点仍渲染", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <div>
        <ErrorBoundary label="say">
          <Boom />
        </ErrorBoundary>
        <div>sibling</div>
      </div>,
    );
    expect(screen.getByTestId("card-degraded")).toBeTruthy();
    expect(screen.getByText("sibling")).toBeTruthy();
  });
});
