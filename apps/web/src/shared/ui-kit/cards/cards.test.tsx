import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApprovalCard } from "./ApprovalCard";
import { AskCard } from "./AskCard";
import { CompactionCard } from "./CompactionCard";
import { SayCard } from "./SayCard";
import { TodoCard } from "./TodoCard";
import { ToolCard } from "./ToolCard";

describe("对话五卡", () => {
  it("SayCard 渲染全文并可复制", async () => {
    render(<SayCard text="hello" streaming={false} />);
    expect(screen.getByText("hello")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "复制" }));
    expect(screen.getByRole("button", { name: "已复制" })).toBeTruthy();
  });

  it("ToolCard 展开/收起输出", async () => {
    render(<ToolCard tool="read_file" status="done" output="line1" />);
    await userEvent.click(screen.getByRole("button", { name: "展开" }));
    expect(screen.getByText("line1")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "收起" }));
    expect(screen.queryByText("line1")).toBeNull();
  });

  it("ApprovalCard 三档按钮回调并展示 detail", async () => {
    const onDecide = vi.fn();
    render(<ApprovalCard tool="edit_file" subject="src/a.ts" detail="+1/-1" onDecide={onDecide} />);
    expect(screen.getByText("+1/-1")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "允许" }));
    await userEvent.click(screen.getByRole("button", { name: "拒绝" }));
    expect(onDecide.mock.calls).toEqual([[true], [false]]);
  });

  it("AskCard 提交输入", async () => {
    const onAnswer = vi.fn();
    render(<AskCard question="which?" onAnswer={onAnswer} />);
    await userEvent.type(screen.getByRole("textbox"), "a.ts");
    await userEvent.click(screen.getByRole("button", { name: "回答" }));
    expect(onAnswer).toHaveBeenCalledWith("a.ts");
  });

  it("CompactionCard 显示 phase/status", () => {
    render(<CompactionCard phase="compact_end" status="progress" />);
    expect(screen.getByText(/compact_end/)).toBeTruthy();
  });

  it("TodoCard 显示路径、完成计数与逐项勾选态", () => {
    render(
      <TodoCard
        path="TODO.md"
        rows={[
          { text: "写文档", checked: true },
          { text: "补测试", checked: false },
        ]}
      />,
    );
    expect(screen.getByText(/TODO\.md/)).toBeTruthy();
    expect(screen.getByText(/1\/2/)).toBeTruthy();
    expect(screen.getByText("写文档")).toBeTruthy();
    expect(screen.getByText("补测试")).toBeTruthy();
  });

  it("TodoCard 空清单给空态而不是空白卡", () => {
    render(<TodoCard path="TODO.md" rows={[]} />);
    expect(screen.getByText("还没有清单项")).toBeTruthy();
  });
});
