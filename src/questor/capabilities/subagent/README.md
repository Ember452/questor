# capabilities/subagent — reserved stub (empty until P8)

Sub-agent orchestration (spawn/lease/mailbox, wuu `agentcontrol`-style) and the
DAG scheduler are P8 (ROADMAP §1). P0/P1 only reserve the `TaskNode.kind=subagent`
field and `assigned_run_id` hook in `contracts` — no engine here yet.
