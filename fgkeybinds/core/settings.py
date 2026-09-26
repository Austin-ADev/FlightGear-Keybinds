"""Réglages persistants de l'application (%APPDATA%/FGKeybinds/settings.json)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


def app_dir() -> Path:
    base = os.environ.get("APPDATA")
    d = (Path(base) if base else Path.home() / ".config") / "FGKeybinds"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Settings:
    fg_root: str = ""
    fg_home: str = ""
    extra_aircraft_dirs: list[str] = field(default_factory=list)
    layout: str = ""
    last_context: str = ""  # "" = global, sinon chemin du -set.xml
    device_kinds: dict[str, str] = field(default_factory=dict)  # nom du périphérique -> type d'illustration
    search_all_joysticks: bool = False
    confirmed_root_write: bool = False
    window_geometry: str = ""

    @classmethod
    def path(cls) -> Path:
        return app_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        p = cls.path()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        s = cls()
        for k, v in data.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s

    def save(self) -> None:
        try:
            self.path().write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass


def journal_path() -> Path:
    """Journal des modifications apportées au clavier global (pour les réappliquer)."""
    return app_dir() / "global-changes.json"


def user_actions_path() -> Path:
    return app_dir() / "actions.json"


def user_layouts_dir() -> Path:
    d = app_dir() / "layouts"
    return d


def optional_path(s: str) -> Optional[str]:
    return s or None
