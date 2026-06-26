# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Gang of Four.

Produces, per platform:
  - Windows / Linux : a single-file executable (GangOfFour[.exe])
  - macOS           : a GangOfFour.app bundle

Build locally with:  pyinstaller gang-of-four.spec
(CI runs exactly this on each OS — see .github/workflows/build.yml)
"""

import glob
import os
import shutil
import sys

APP_NAME = "GangOfFour"

icon = None
if sys.platform == "win32":
    icon = "assets/icon.ico"
elif sys.platform == "darwin":
    icon = "assets/icon.icns"

# --------------------------------------------------------------------------- #
# Tesseract OCR bundling
# Locate the tesseract binary and eng/osd traineddata on the build machine,
# then include them so the frozen app can OCR scanned PDFs without any extra
# install step on the user's machine.
# --------------------------------------------------------------------------- #
_tess_bin = shutil.which("tesseract")

# Windows: choco may not add to PATH yet — check the fixed install dir.
if sys.platform == "win32" and not _tess_bin:
    _win_default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.isfile(_win_default):
        _tess_bin = _win_default

_tess_binaries = [((_tess_bin, "."))] if _tess_bin else []

# Locate tessdata directory on the build machine.
if sys.platform == "win32":
    _tess_data_src = os.path.join(os.path.dirname(_tess_bin), "tessdata") if _tess_bin else ""
elif sys.platform == "darwin":
    _tess_data_src = next(
        (d for d in ("/opt/homebrew/share/tessdata", "/usr/local/share/tessdata")
         if os.path.isdir(d)), ""
    )
else:  # Linux
    _tess_data_src = next(
        (d for d in ("/usr/share/tesseract-ocr/5/tessdata",
                     "/usr/share/tesseract-ocr/4.00/tessdata",
                     "/usr/share/tessdata")
         if os.path.isdir(d)), ""
    )

# Bundle only the two files needed for English OCR (~16 MB total).
_tess_datas = [
    (os.path.join(_tess_data_src, name), "tessdata")
    for name in ("eng.traineddata", "osd.traineddata")
    if _tess_data_src and os.path.isfile(os.path.join(_tess_data_src, name))
]

# --------------------------------------------------------------------------- #
# libxcb-cursor bundling (Linux)
# Qt's XCB platform plugin requires libxcb-cursor.so.0, but it is not
# universally installed (the libxcb-cursor0 package is absent on some distros
# and older Ubuntu versions).  Bundle it so the frozen app works out of the box.
# --------------------------------------------------------------------------- #
if sys.platform == "linux":
    _xcb_cursor = next(
        iter(
            glob.glob("/usr/lib/*/libxcb-cursor.so.0")
            + glob.glob("/usr/lib/libxcb-cursor.so.0")
        ),
        None,
    )
    _xcb_cursor_binaries = [(_xcb_cursor, ".")] if _xcb_cursor else []
else:
    _xcb_cursor_binaries = []

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=_tess_binaries + _xcb_cursor_binaries,
    datas=[("assets", "assets")] + _tess_datas,  # assets + tessdata
    hiddenimports=["fitz", "fitz._fitz", "docx", "pptx", "openpyxl"],
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
