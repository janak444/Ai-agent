# -*- mode: python ; coding: utf-8 -*-
# Devsoft-Agentic IDE — PyInstaller spec
# Build:  pyinstaller Devsoft-Agentic.spec
# Output: dist/Devsoft-Agentic IDE(.app|.exe)

import sys
from PyInstaller.utils.hooks import collect_all

APP_NAME = "Devsoft-Agentic IDE"

ctk_datas, ctk_bins, ctk_hidden = collect_all("customtkinter")
pillow_datas, pillow_bins, pillow_hidden = collect_all("PIL")

a = Analysis(
    ["run_gui.py"],
    pathex=[],
    binaries=ctk_bins + pillow_bins,
    datas=ctk_datas + pillow_datas,
    hiddenimports=ctk_hidden + pillow_hidden + ["httpx2", "ollama"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "unittest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="com.devsoft.agenticide",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.developer-tools",
        },
    )
