"""Détection des dossiers de FlightGear (FG_ROOT, FG_HOME, dossiers d'avions)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def default_fg_home() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "flightgear.org"
    return Path.home() / ".fgfs"


def _is_fg_root(p: Path) -> bool:
    return (p / "keyboard.xml").is_file() and (p / "Input").is_dir()


def read_fg_version(fg_root: Path) -> str:
    try:
        return (fg_root / "version").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _launcher_ini(fg_home: Path) -> Optional[Path]:
    """Fichier de réglages du lanceur Qt le plus récent (FlightGear_2024.1.ini...)."""
    cands = sorted((fg_home / "FlightGear").glob("FlightGear*.ini"), key=lambda p: p.stat().st_mtime,
                   reverse=True) if (fg_home / "FlightGear").is_dir() else []
    return cands[0] if cands else None


def _ini_values(ini: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in ini.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.startswith("["):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _split_qt_list(v: str) -> list[str]:
    v = v.strip()
    if v.startswith("@") or not v:
        return []
    parts = [x.strip().strip('"') for x in v.split(",")]
    return [p for p in parts if p]


def _log_options(fg_home: Path) -> dict[str, str]:
    """Options lues dans le dernier fgfs.log (fg-root, fg-aircraft...)."""
    out: dict[str, str] = {}
    log = fg_home / "fgfs.log"
    if not log.is_file():
        return out
    try:
        with log.open("r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i > 400:
                    break
                m = re.search(r"option:([\w-]+)\s*=\s*(.*)$", line)
                if m:
                    out[m.group(1)] = m.group(2).strip()
    except OSError:
        pass
    return out


@dataclass
class FGPaths:
    fg_root: Optional[Path]
    fg_home: Path
    aircraft_dirs: list[Path] = field(default_factory=list)
    download_dir: Optional[Path] = None

    @property
    def version(self) -> str:
        return read_fg_version(self.fg_root) if self.fg_root else ""

    @property
    def user_joystick_dir(self) -> Path:
        return self.fg_home / "Input" / "Joysticks"


def detect(
    fg_root_override: Optional[str] = None,
    fg_home_override: Optional[str] = None,
    extra_aircraft_dirs: Optional[list[str]] = None,
) -> FGPaths:
    fg_home = Path(fg_home_override) if fg_home_override else Path(os.environ.get("FG_HOME") or default_fg_home())
    ini = _launcher_ini(fg_home)
    ini_vals = _ini_values(ini) if ini else {}
    log_opts = _log_options(fg_home)

    download_dir = None
    if ini_vals.get("download-dir"):
        download_dir = Path(ini_vals["download-dir"].strip('"'))

    # --- FG_ROOT ---------------------------------------------------------
    candidates: list[Path] = []
    if fg_root_override:
        candidates.append(Path(fg_root_override))
    if os.environ.get("FG_ROOT"):
        candidates.append(Path(os.environ["FG_ROOT"]))
    if log_opts.get("fg-root"):
        candidates.append(Path(log_opts["fg-root"]))
    if download_dir and download_dir.is_dir():
        candidates += sorted(download_dir.glob("fgdata*"), reverse=True)
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), "C:/Program Files",
                 "D:/Program Files", "E:/Program Files"):
        if base and Path(base).is_dir():
            for d in sorted(Path(base).glob("FlightGear*"), reverse=True):
                candidates += [d / "data", d]
    steam = Path("C:/Program Files (x86)/Steam/steamapps/common/FlightGear/data")
    candidates.append(steam)
    fg_root = next((c for c in candidates if _is_fg_root(c)), None)

    # --- dossiers d'avions --------------------------------------------------
    dirs: list[Path] = []
    if fg_root:
        dirs.append(fg_root / "Aircraft")
    if download_dir:
        # le lanceur installe dans <download-dir>/Aircraft/<catalogue>/Aircraft
        dirs += [p / "Aircraft" for p in sorted((download_dir / "Aircraft").glob("*"))
                 if (p / "Aircraft").is_dir()]
    for key in ("aircraft-paths", "aircraft-dirs"):
        dirs += [Path(p) for p in _split_qt_list(ini_vals.get(key, ""))]
    for p in (log_opts.get("fg-aircraft") or "").split(os.pathsep):
        if p.strip():
            dirs.append(Path(p.strip()))
    for p in (os.environ.get("FG_AIRCRAFT") or "").split(os.pathsep):
        if p.strip():
            dirs.append(Path(p.strip()))
    for p in extra_aircraft_dirs or []:
        dirs.append(Path(p))
    uniq: list[Path] = []
    seen = set()
    for d in dirs:
        try:
            key = str(d.resolve()).lower()
        except OSError:
            continue
        if key not in seen and d.is_dir():
            seen.add(key)
            uniq.append(d)
    return FGPaths(fg_root=fg_root, fg_home=fg_home, aircraft_dirs=uniq, download_dir=download_dir)
