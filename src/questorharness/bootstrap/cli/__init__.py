"""Command-line entry package: the Typer app plus one module per command group.

The package root exports nothing on purpose -- importing ``questorharness`` must not
pull in typer. The console scripts point at ``questorharness.bootstrap.cli.main:app``.
"""

__all__: list[str] = []
