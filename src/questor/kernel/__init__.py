"""L2 Kernel/Harness — pure mechanism: turn loop, event bus, permissions.

Decides and wraps; never touches models or UI directly (DeepCode discipline).
Depends on :mod:`questor.contracts` + :mod:`questor.state` and injected Ports
only — must not import policy/surfaces implementations (C1/C14)."""
