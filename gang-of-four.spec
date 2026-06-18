# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Gang of Four.

Produces, per platform:
  - Windows / Linux : a single-file executable (GangOfFour[.exe])
  - macOS           : a GangOfFour.app bundle

Build locally with:  pyinstaller gang-of-four.spec
(CI runs exactly this on each OS — see .github/workflows/build.yml)
"""

import sys

APP_NAME = "GangOfFour"

icon = None
if sys.platform == "win32":
    icon = "assets/icon.ico"
elif sys.platform == "darwin":
    icon = "assets/icon.icns"

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[("assets", "assets")],  # unpacked to <bundle>/assets at runtime
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # One-dir build wrapped in a .app bundle (the macOS-native form).
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name=APP_NAME,
        console=False,
        icon=icon,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="com.henryespinosa.gangoffour",
        info_plist={"NSHighResolutionCapable": True},
    )
else:
    # Single-file executable for Windows and Linux (binaries + datas folded
    # into EXE, with no COLLECT, is what makes it one-file).
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name=APP_NAME,
        console=False,
        icon=icon,
    )
