# -*- mode: python ; coding: utf-8 -*-
# Questor 引擎（onedir）。onefile 被拒绝：启动自解压会让父租约/握手时序不可控。
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

REPO = Path(SPECPATH).resolve().parents[2]
SRC = REPO / "src"

hiddenimports = collect_submodules("questorharness") + collect_submodules("questor")

# profile bundle 是数据文件：default_profile_root 在冻结后指向 <_internal>/questor/profiles。
datas = [(str(SRC / "questor/profiles"), "questor/profiles")]

a = Analysis(
    [str(SRC / "questorharness/__main__.py")],
    pathex=[str(SRC)],
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib"],
    datas=datas,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="questor-engine",
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, name="engine")
