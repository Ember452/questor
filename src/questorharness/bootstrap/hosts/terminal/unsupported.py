"""未实现能力的徽标登记表（渲染侧真源）。

id 三处相等：本表、`docs/plan/mapping/terminal-coding.md` 的 id 列、plan03 §0.5 表 A。
`tests/ci/test_unsupported_badges.py` 做双向断言——多一个 id 表示渲染了没登记的能力，
少一个 id 表示真功能黑洞。值 = (名词, 缺失原因)；名词进徽标，原因进展开说明。
"""

from __future__ import annotations

from questorharness.bootstrap.hosts.terminal import strings

UNSUPPORTED: dict[str, tuple[str, str]] = {
    "A1": ("审批第三档", "缺三态 PermissionPrompt（runtime.py:55 返回 bool）"),
    "A2": ("Ask 选项/多选", "引擎回调只收自由文本（ask_user_question_tool.py:12）"),
    "A3": ("回合中插话", "无 /steer 端点，authority 只有 1 个排队槽"),
    "A5": ("图片/附件提交", "/submit 无 attachments 字段"),
    "A6": ("语音采集", "/voice 只是设置开关"),
}


def badge_text(gap_id: str) -> str:
    """渲染用的一行文本，形如 `⊘ 未实现 · A1 审批第三档`。

    未登记的 id 立刻 KeyError：宁可崩在测试里，也不在用户屏幕上写一个
    没有来源的"未实现"。
    """

    name, _reason = UNSUPPORTED[gap_id]
    return strings.BADGE_FORMAT.format(
        mark=strings.BADGE_MARK, gap_id=gap_id, name=name
    )


def badge_reason(gap_id: str) -> str:
    """展开说明：缺的是哪条后端契约，供 `/help` 与徽标详情复用。"""

    return UNSUPPORTED[gap_id][1]
