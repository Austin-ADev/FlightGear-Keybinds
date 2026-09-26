# -*- mode: python ; coding: utf-8 -*-
# Construction : pyinstaller FGKeybinds.spec   (voir build.ps1)
import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

ROOT = Path(SPECPATH)
version = re.search(r'__version__ = "([^"]+)"', (ROOT / "fgkeybinds" / "__init__.py").read_text(encoding="utf-8")).group(1)
nums = tuple(int(x) for x in re.findall(r"\d+", version)[:3]) + (0,)

vinfo = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nums, prodvers=nums),
    kids=[
        StringFileInfo([StringTable("040C04B0", [
            StringStruct("CompanyName", "FGKeybinds"),
            StringStruct("FileDescription", "FGKeybinds - raccourcis clavier et périphériques de FlightGear"),
            StringStruct("FileVersion", version),
            StringStruct("InternalName", "FGKeybinds"),
            StringStruct("OriginalFilename", "FGKeybinds.exe"),
            StringStruct("ProductName", "FGKeybinds"),
            StringStruct("ProductVersion", version),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x040C, 1200])]),
    ],
)

a = Analysis(
    ["FGKeybinds.pyw"],
    pathex=[str(ROOT)],
    datas=[("fgkeybinds/data", "fgkeybinds/data")],
    hiddenimports=["PySide6.QtSvg"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtNetwork"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="FGKeybinds",
    icon=str(ROOT / "build" / "fgkeybinds.ico"),
    version=vinfo,
    console=False,
    upx=False,
    runtime_tmpdir=None,
)
