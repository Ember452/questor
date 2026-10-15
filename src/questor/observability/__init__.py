"""Cross-cutting: logging, event-sourcing queries, trace (read-only reporting).

Depends only on :mod:`questor.contracts`; never imports kernel/policy impl and
never mutates state (STRUCTURE S7)."""
