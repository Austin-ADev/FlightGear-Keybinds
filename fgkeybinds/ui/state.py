"""State shared between interface pages."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from ..core.layouts import Layout, detect_system_layout
from ..core.settings import Settings
from ..core.workspace import GLOBAL, Context, Workspace


class AppState(QObject):
    contextChanged = Signal()
    dataChanged = Signal()  # après une écriture ou un rechargement
    layoutChanged = Signal()
    devicesChanged = Signal()
    labelsChanged = Signal()  # descriptions d'aéronefs chargées
    navigateKey = Signal(int, int)  # code, masque
    navigateControl = Signal(str, str, int, str)  # chemin de config, type (axis/button), index, nom du périphérique
    status = Signal(str)

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.ws = Workspace(settings)
        self._context = GLOBAL
        if settings.last_context:
            v = self.ws.variant(settings.last_context)
            if v is not None:
                self._context = Context("aircraft", v.set_file)
        lid = settings.layout or detect_system_layout()
        self._layout = next((l for l in self.ws.layouts if l.id == lid), self.ws.layouts[0])

    # -- contexte ---------------------------------------------------------
    @property
    def context(self) -> Context:
        return self._context

    def set_context(self, ctx: Context) -> None:
        if ctx == self._context:
            return
        self._context = ctx
        self.settings.last_context = ctx.key
        self.settings.save()
        self.contextChanged.emit()

    @property
    def keyboard(self):
        return self.ws.keyboard(self._context)

    # -- disposition ------------------------------------------------------
    @property
    def layout(self) -> Layout:
        return self._layout

    def set_layout(self, lid: str) -> None:
        lay = next((l for l in self.ws.layouts if l.id == lid), None)
        if lay is None or lay is self._layout:
            return
        self._layout = lay
        self.settings.layout = lid
        self.settings.save()
        self.layoutChanged.emit()

    # -- rechargement -----------------------------------------------------
    def reload(self) -> None:
        self.ws.reload()
        if not self._context.is_global and self.ws.variant(self._context.set_file) is None:
            self._context = GLOBAL
            self.contextChanged.emit()
        self.dataChanged.emit()
        self.devicesChanged.emit()

    def after_write(self, path: Optional[Path] = None) -> None:
        self.dataChanged.emit()
        msg = f"Enregistré : {path}" if path else "Changes saved."
        if fg_running():
            msg += "  —  FlightGear has been launched: restart it to apply the changes."
        self.status.emit(msg)


def fg_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq fgfs.exe", "/NH"], capture_output=True, text=True, timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        return "fgfs.exe" in out.lower()
    except (OSError, subprocess.SubprocessError):
        return False
