"""Entry point (Python sidecar start point in later phases).

In P0 there is **no runnable Agent behavior** by design (ROADMAP §1.5). Running
this module only confirms the package is wired; the interactive loop arrives in
P1 (``docs/plan/01-p1-minimal-loop.md``).
"""

from questor.version import __version__


def main() -> int:
    print(f"questor {__version__} (P0 interface skeleton — no runnable agent yet).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
