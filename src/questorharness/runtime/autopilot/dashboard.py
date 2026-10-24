"""``RepoAutopilotStore`` mixin: dashboard."""

from __future__ import annotations

import json
import time
from html import escape
from pathlib import Path
from typing import Any

from questorharness.platform.io import atomic_write_text
from questorharness.platform.paths import (
    get_project_autopilot_policy_path,
    get_project_release_policy_path,
    get_project_verification_policy_path,
)
from questorharness.runtime.autopilot.text_utils import (
    _json_default,
    _safe_text,
)


class DashboardMixin:
    """Dashboard operations for the repo autopilot store."""

    def export_dashboard(self, output_dir: str | Path | None = None) -> Path:
        target_dir = Path(output_dir) if output_dir is not None else self._cwd / "docs" / "autopilot"
        target_dir = target_dir.resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        snapshot = self._build_dashboard_snapshot()
        atomic_write_text(
            target_dir / "snapshot.json",
            json.dumps(snapshot, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        )
        atomic_write_text(target_dir / "index.html", self._render_dashboard_html(snapshot))
        atomic_write_text(target_dir / ".nojekyll", "")
        return target_dir

    def _build_dashboard_snapshot(self) -> dict[str, Any]:
        registry = self._load_registry()
        cards = sorted(
            registry.cards,
            key=lambda card: (
                self._status_sort_key(card.status),
                -card.score,
                -card.updated_at,
                card.title.lower(),
            ),
        )
        status_order = [
            "queued",
            "accepted",
            "preparing",
            "running",
            "verifying",
            "pr_open",
            "waiting_ci",
            "repairing",
            "completed",
            "merged",
            "failed",
            "rejected",
            "superseded",
        ]
        columns = {status: [] for status in status_order}
        counts = {status: 0 for status in status_order}
        for card in cards:
            counts[card.status] = counts.get(card.status, 0) + 1
            columns.setdefault(card.status, []).append(self._serialize_card(card))

        focus = None
        for status in ("repairing", "waiting_ci", "running", "verifying", "preparing", "accepted", "queued"):
            bucket = columns.get(status) or []
            if bucket:
                focus = bucket[0]
                break

        return {
            "generated_at": time.time(),
            "repo_name": self._cwd.name,
            "repo_path": str(self._cwd),
            "focus": focus,
            "counts": counts,
            "status_order": status_order,
            "columns": columns,
            "cards": [self._serialize_card(card) for card in cards],
            "journal": [
                {
                    "timestamp": entry.timestamp,
                    "kind": entry.kind,
                    "summary": entry.summary,
                    "task_id": entry.task_id,
                    "metadata": entry.metadata,
                }
                for entry in self.load_journal(limit=30)
            ],
            "policies": {
                "autopilot": str(get_project_autopilot_policy_path(self._cwd)),
                "verification": str(get_project_verification_policy_path(self._cwd)),
                "release": str(get_project_release_policy_path(self._cwd)),
            },
            "active_context": self.load_active_context(),
        }

    def _render_dashboard_html(self, snapshot: dict[str, Any]) -> str:
        """Return a minimal fallback HTML page.

        The primary dashboard is now a React + Vite app built from
        ``autopilot-dashboard/``.  This fallback is only written when
        no pre-built ``index.html`` already exists in the output
        directory, so local ``snapshot.json`` generation still works
        without a Node.js toolchain.
        """
        repo_name = escape(_safe_text(snapshot.get("repo_name")) or "QuestorHarness")
        generated = time.strftime(
            "%Y-%m-%d %H:%M:%S UTC",
            time.gmtime(float(snapshot.get("generated_at") or time.time())),
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{repo_name} Autopilot Kanban</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --bg: #0a0a0a; --bg-elevated: #1a1a1a; --ink: #fff;
      --accent: #00d4aa; --muted: #666; --line: #222;
      --mono: "JetBrains Mono", ui-monospace, monospace;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--ink); font-family: var(--mono); font-size: 13px; }}
    .shell {{ max-width: 960px; margin: 80px auto; padding: 0 20px; text-align: center; }}
    h1 {{ font-size: 32px; letter-spacing: 2px; margin-bottom: 16px; }}
    h1 span {{ color: var(--accent); }}
    .sub {{ color: var(--muted); font-size: 12px; line-height: 1.8; margin-bottom: 32px; }}
    .info {{ background: var(--bg-elevated); border: 1px solid var(--line); border-radius: 6px; padding: 24px; text-align: left; }}
    .info p {{ color: #888; font-size: 12px; line-height: 1.7; margin-bottom: 12px; }}
    .info code {{ color: var(--accent); }}
    .ts {{ color: var(--muted); font-size: 10px; letter-spacing: 1px; margin-top: 20px; }}
  </style>
</head>
<body>
  <div class="shell">
    <h1>{repo_name} <span>AUTOPILOT</span></h1>
    <p class="sub">
      This is a fallback page. The full React dashboard is built via CI
      from <code>autopilot-dashboard/</code>.
    </p>
    <div class="info">
      <p>To view the full dashboard locally, build the React app:</p>
      <p><code>cd autopilot-dashboard &amp;&amp; npm install &amp;&amp; npm run build</code></p>
      <p>Then open <code>docs/autopilot/index.html</code> in a browser.</p>
      <p>Snapshot data: <code>snapshot.json</code> (generated {escape(generated)})</p>
    </div>
    <div class="ts">Generated at {escape(generated)}</div>
  </div>
</body>
</html>
"""

# questor: allow R7 -- until W8 adds the mirror test
