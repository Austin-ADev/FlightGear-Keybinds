"""Capture d'une combinaison de touches ou d'une commande de périphérique."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..core import joystick
from ..core.bindings import MOD_ALT, MOD_CTRL, MOD_META, MOD_SHIFT
from ..core.keyboard import KeyboardConfig, combo_label
from ..core.search import physical_hint
from ..core.layouts import Layout
from . import theme

_QT_SPECIAL = {
    Qt.Key_Escape: 27, Qt.Key_Tab: 9, Qt.Key_Backtab: 9, Qt.Key_Backspace: 8, Qt.Key_Return: 13,
    Qt.Key_Enter: 13, Qt.Key_Delete: 127, Qt.Key_Insert: 364, Qt.Key_Home: 362, Qt.Key_End: 363,
    Qt.Key_PageUp: 360, Qt.Key_PageDown: 361, Qt.Key_Left: 356, Qt.Key_Up: 357, Qt.Key_Right: 358,
    Qt.Key_Down: 359, Qt.Key_Space: 32, Qt.Key_Clear: 309,
}
for _i in range(12):
    _QT_SPECIAL[getattr(Qt, f"Key_F{_i + 1}")] = 257 + _i

_MODIFIER_KEYS = {Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_AltGr, Qt.Key_Meta, Qt.Key_CapsLock,
                  Qt.Key_NumLock, Qt.Key_ScrollLock}


def event_to_fg(ev: QKeyEvent) -> Optional[tuple[int, int]]:
    """Traduit un QKeyEvent en (code FlightGear, masque de modificateurs)."""
    key = ev.key()
    if key in _MODIFIER_KEYS or key == 0:
        return None
    mods = ev.modifiers()
    mask = 0
    if mods & Qt.ShiftModifier:
        mask |= MOD_SHIFT
    if mods & Qt.ControlModifier:
        mask |= MOD_CTRL
    if mods & Qt.AltModifier:
        mask |= MOD_ALT
    if mods & Qt.MetaModifier:
        mask |= MOD_META
    keypad = bool(mods & Qt.KeypadModifier)
    text = ev.text()
    if keypad:
        if key == Qt.Key_Enter:
            return 269, mask
        if text and text[0] in "0123456789.+-*/":
            return ord(text[0]), mask
        if Qt.Key_0 <= key <= Qt.Key_9:
            return ord("0") + (key - Qt.Key_0), mask
    if key in _QT_SPECIAL:
        return _QT_SPECIAL[key], mask
    # Ctrl + lettre : code de contrôle (1 à 26)
    if mask & MOD_CTRL and not (mask & MOD_ALT) and Qt.Key_A <= key <= Qt.Key_Z:
        return key - Qt.Key_A + 1, mask
    if text and ord(text[0]) >= 32 and ord(text[0]) != 127:
        return ord(text[0]), mask
    if 32 < key < 0x110000:
        c = chr(key)
        if not (mask & MOD_SHIFT):
            c = c.lower()
        return ord(c), mask
    return None


class KeyCaptureDialog(QDialog):
    """Attend une combinaison de touches et affiche l'action qu'elle déclenche."""

    def __init__(self, parent, layout: Layout, kb: Optional[KeyboardConfig], title: str = "Capturer une touche",
                 purpose: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self.layout_ = layout
        self.kb = kb
        self.result_combo: Optional[tuple[int, int]] = None
        lay = QVBoxLayout(self)
        t = QLabel("Appuyez sur la combinaison de touches…")
        t.setProperty("heading", True)
        lay.addWidget(t)
        if purpose:
            p = QLabel(purpose)
            p.setProperty("muted", True)
            p.setWordWrap(True)
            lay.addWidget(p)
        self.combo = QLabel("—")
        self.combo.setAlignment(Qt.AlignCenter)
        self.combo.setStyleSheet(f"font-size: 22pt; font-weight: 700; color: {theme.ACCENT}; padding: 16px;"
                                 f"background: {theme.BG}; border: 1px solid {theme.BORDER}; border-radius: 8px;")
        lay.addWidget(self.combo)
        self.info = QLabel(" ")
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        lay.addWidget(self.info)
        hl = QHBoxLayout()
        hl.addStretch(1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_ok = QPushButton("Valider")
        self.btn_ok.setProperty("primary", True)
        self.btn_ok.setEnabled(False)
        for b in (self.btn_cancel, self.btn_ok):
            b.setFocusPolicy(Qt.NoFocus)
            hl.addWidget(b)
        lay.addLayout(hl)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self.accept)
        self.setFocusPolicy(Qt.StrongFocus)

    def event(self, ev) -> bool:
        # intercepter Tab / Échap / Entrée avant la navigation standard du dialogue
        if ev.type() == QEvent.KeyPress:
            self._key(ev)
            return True
        if ev.type() == QEvent.ShortcutOverride:
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        self._key(ev)

    def _key(self, ev: QKeyEvent) -> None:
        r = event_to_fg(ev)
        if r is None:
            return
        self.result_combo = r
        code, mask = r
        self.combo.setText(combo_label(code, mask))
        lines = [f"<span style='color:{theme.MUTED}'>Code FlightGear {code}</span>"]
        hint = physical_hint(self.layout_, code, mask)
        if hint:
            lines.append(f"<span style='color:{theme.MUTED}'>Touche sur le clavier {self.layout_.name} : {hint}</span>")
        if self.kb is not None:
            res = self.kb.resolve(code, mask)
            if res.slot is not None and res.slot.is_bound:
                pre = "↺ par repli : " if res.fallback else ""
                lines.append(f"Action actuelle : <b>{pre}{res.slot.description()}</b>")
            else:
                lines.append(f"<span style='color:{theme.GREEN}'>Combinaison libre.</span>")
        self.info.setText("<br>".join(lines))
        self.btn_ok.setEnabled(True)


class JoystickCaptureDialog(QDialog):
    """Attend l'appui sur un bouton ou le mouvement d'un axe d'un périphérique."""

    def __init__(self, parent, devices: list[joystick.Device], want: str = "any"):
        super().__init__(parent)
        self.setWindowTitle("Identifier une commande")
        self.setMinimumWidth(460)
        self.devices = devices
        self.want = want  # any | button | axis
        self.result_control: Optional[tuple[joystick.Device, str, int]] = None
        self._base: dict[int, joystick.DeviceState] = {}
        lay = QVBoxLayout(self)
        what = {"any": "Appuyez sur un bouton ou bougez un axe",
                "button": "Appuyez sur un bouton", "axis": "Bougez franchement un axe"}[want]
        t = QLabel(what + "…")
        t.setProperty("heading", True)
        lay.addWidget(t)
        self.info = QLabel("En attente d'une action sur l'un des périphériques branchés.")
        self.info.setProperty("muted", True)
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.found = QLabel("—")
        self.found.setAlignment(Qt.AlignCenter)
        self.found.setStyleSheet(f"font-size: 16pt; font-weight: 700; color: {theme.ACCENT}; padding: 14px;"
                                 f"background: {theme.BG}; border: 1px solid {theme.BORDER}; border-radius: 8px;")
        lay.addWidget(self.found)
        hl = QHBoxLayout()
        hl.addStretch(1)
        cancel = QPushButton("Cancel")
        self.ok = QPushButton("Valider")
        self.ok.setProperty("primary", True)
        self.ok.setEnabled(False)
        hl.addWidget(cancel)
        hl.addWidget(self.ok)
        lay.addLayout(hl)
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.accept)
        for d in devices:
            st = d.poll()
            if st is not None:
                self._base[d.id] = st
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(30)
        if not devices:
            self.info.setText("Aucun périphérique de jeu n'est branché.")

    def _poll(self) -> None:
        for d in self.devices:
            st = d.poll()
            base = self._base.get(d.id)
            if st is None or base is None:
                continue
            if self.want in ("any", "button"):
                newly = st.buttons & ~base.buttons
                if newly:
                    i = (newly & -newly).bit_length() - 1
                    self._set(d, "button", i)
                    return
            if self.want in ("any", "axis"):
                for i, (a, b) in enumerate(zip(st.axes, base.axes)):
                    if abs(a - b) > 0.5:
                        self._set(d, "axis", i)
                        self._base[d.id] = st
                        return

    def _set(self, d: joystick.Device, typ: str, i: int) -> None:
        self.result_control = (d, typ, i)
        if typ == "button":
            self.found.setText(f"{d.name}\nBouton {i}")
        else:
            self.found.setText(f"{d.name}\nAxe {i} ({joystick.AXIS_NAMES_WIN[i]})")
        self.ok.setEnabled(True)

    def done(self, r: int) -> None:
        self.timer.stop()
        super().done(r)
