# Staging dir for the frozen sidecar (three-stage step ③ input)

`desktop/scripts/build-sidecar.py` copies the PyInstaller **onedir** output to
`sidecar/questor-sidecar/` here (merged, non-destructively); `tauri.conf.json` bundles it via
`bundle.resources`, and the shell's `resolve_sidecar` loads it from
`resource_dir/sidecar/questor-sidecar/questor-sidecar(.exe)` so a **released** app never falls back
to a system `python`.

The onedir contents are build artifacts (gitignored); this tracked placeholder keeps the directory
present so `tauri-build` (run by `cargo check`/`clippy`) doesn't fail on a missing resources
directory in a clean checkout.
