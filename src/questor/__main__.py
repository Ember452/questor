"""Entry point: launches the CLI terminal surface (the P1 interactive demo).

Run with ``python -m questor``. The Python sidecar / Tauri launch point is added
in later phases; for P1 this starts the terminal "ask one line, stream one answer".
"""

from questor.surfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
