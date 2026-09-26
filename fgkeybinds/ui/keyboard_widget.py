"""Dessin interactif d'un clavier avec les actions associées à chaque touche."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolTip, QWidget

from ..core.keyboard import KeyboardConfig, combo_label
from ..core.layouts import LAYER_MASK, Layout, PhysKey
from . import theme

GAP = 0.06  # espace entre touches, en unités de touche
MOD_KEY_LAYERS = {
    "LSHIFT": {"shift", "ctrl+shift", "alt+shift"},
    "RSHIFT": {"shift", "ctrl+shift", "alt+shift"},
    "LCTRL": {"ctrl", "ctrl+shift"},
    "RCTRL": {"ctrl", "ctrl+shift"},
    "LALT": {"alt", "alt+shift"},
    "RALT": {"altgr"},
}


@dataclass
class KeyVisual:
    origin: str  # global | aircraft | disabled | none | modifier
    glyph: str
    action: str
    combo: str
    fallback: bool = False
    code: Optional[int] = None
    mask: int = 0
    release_only: bool = False


def wrap_elide(text: str, fm: QFontMetricsF, width: float, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    i = 0
    while i < len(words):
        w = words[i]
        cand = (cur + " " + w).strip()
        if fm.horizontalAdvance(cand) <= width:
            cur = cand
            i += 1
            continue
        if not cur:
            # mot trop long : coupé
            lines.append(fm.elidedText(w, Qt.ElideRight, width))
            i += 1
        else:
            lines.append(cur)
            cur = ""
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
        cur = ""
    if (i < len(words) or cur) and lines:
        rest = " ".join([lines[-1]] + ([cur] if cur else []) + words[i:])
        lines[-1] = fm.elidedText(rest, Qt.ElideRight, width)
    return lines


class KeyboardWidget(QWidget):
    keyClicked = Signal(str)
    keyDoubleClicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_: Optional[Layout] = None
        self.kb: Optional[KeyboardConfig] = None
        self.layer = "none"
        self.selected: Optional[str] = None
        self.highlight: set[str] = set()
        self.dim_unhighlighted = False
        self.hover: Optional[str] = None
        self._visuals: dict[str, KeyVisual] = {}
        self.setMouseTracking(True)
        self.setMinimumSize(760, 250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # -- données --------------------------------------------------------
    def set_data(self, layout: Layout, kb: KeyboardConfig, layer: str) -> None:
        self.layout_ = layout
        self.kb = kb
        self.layer = layer
        self._compute()
        self.update()

    def set_selected(self, kid: Optional[str]) -> None:
        self.selected = kid
        self.update()

    def set_highlight(self, ids: set[str], dim_others: bool = False) -> None:
        self.highlight = ids
        self.dim_unhighlighted = dim_others and bool(ids)
        self.update()

    def visual(self, kid: str) -> Optional[KeyVisual]:
        return self._visuals.get(kid)

    def _compute(self) -> None:
        self._visuals = {}
        if self.layout_ is None:
            return
        for k in self.layout_.keys:
            self._visuals[k.id] = self._visual_for(k)

    def _visual_for(self, k: PhysKey) -> KeyVisual:
        glyph = self._glyph(k)
        if not k.bindable:
            return KeyVisual("modifier", glyph, "", k.label)
        if self.layer == "altgr" and not self.layout_.has_altgr:
            return KeyVisual("none", glyph, "", "")
        ki = k.input_for(self.layer)
        if ki is None or self.kb is None:
            return KeyVisual("none", glyph, "", "")
        combo = combo_label(ki.code, ki.mask)
        r = self.kb.resolve(ki.code, ki.mask)
        s = r.slot
        if s is not None and s.live_press:
            return KeyVisual(s.origin, glyph, s.description(), combo, r.fallback, ki.code, ki.mask)
        if s is not None and s.is_disabled and not r.fallback:
            return KeyVisual("disabled", glyph, "Désactivé par l'aéronef", combo, False, ki.code, ki.mask)
        # binding uniquement au relâchement ?
        direct = self.kb.slot(ki.code, ki.mask)
        if direct is not None and direct.live_release:
            return KeyVisual(direct.origin, glyph, direct.description(), combo, False, ki.code, ki.mask, True)
        return KeyVisual("none", glyph, "", combo, False, ki.code, ki.mask)

    def _glyph(self, k: PhysKey) -> str:
        if k.kind in ("char", "dead"):
            if self.layer in ("shift", "alt+shift"):
                c = k.shift or ""
            elif self.layer == "altgr":
                c = k.altgr or ""
            else:
                c = k.base or ""
            if c.isalpha() and len(c) == 1 and self.layer not in ("shift", "alt+shift"):
                c = c.upper()
            return c
        return k.label

    # -- géométrie -------------------------------------------------------
    def _metrics(self) -> tuple[float, float, float]:
        if self.layout_ is None:
            return 1.0, 0.0, 0.0
        m = 10.0
        w = self.width() - 2 * m
        h = self.height() - 2 * m
        unit = min(w / self.layout_.width, h / self.layout_.height)
        ox = m + (w - unit * self.layout_.width) / 2
        oy = m + (h - unit * self.layout_.height) / 2
        return unit, ox, oy

    def key_path(self, k: PhysKey) -> QPainterPath:
        unit, ox, oy = self._metrics()
        g = GAP * unit / 2
        r = unit * 0.12
        p = QPainterPath()
        if k.shape == "iso_enter":
            # partie haute large, partie basse décalée
            x0 = ox + k.x * unit + g
            x1 = ox + (k.x + k.w) * unit - g
            xb = ox + (k.x + 0.25) * unit + g
            y0 = oy + k.y * unit + g
            ym = oy + (k.y + 1) * unit - g
            y1 = oy + (k.y + k.h) * unit - g
            p.moveTo(x0 + r, y0)
            p.lineTo(x1 - r, y0)
            p.quadTo(x1, y0, x1, y0 + r)
            p.lineTo(x1, y1 - r)
            p.quadTo(x1, y1, x1 - r, y1)
            p.lineTo(xb + r, y1)
            p.quadTo(xb, y1, xb, y1 - r)
            p.lineTo(xb, ym)
            p.lineTo(x0 + r, ym)
            p.quadTo(x0, ym, x0, ym - r)
            p.lineTo(x0, y0 + r)
            p.quadTo(x0, y0, x0 + r, y0)
            p.closeSubpath()
            return p
        rect = QRectF(ox + k.x * unit + g, oy + k.y * unit + g, k.w * unit - 2 * g, k.h * unit - 2 * g)
        p.addRoundedRect(rect, r, r)
        return p

    def key_at(self, pos: QPointF) -> Optional[PhysKey]:
        if self.layout_ is None:
            return None
        for k in self.layout_.keys:
            if self.key_path(k).contains(pos):
                return k
        return None

    # -- dessin -----------------------------------------------------------
    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.PANEL))
        if self.layout_ is None:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "Aucune disposition de clavier")
            return
        unit, _, _ = self._metrics()
        glyph_font = QFont("Segoe UI", 1)
        glyph_font.setPixelSize(max(8, int(unit * 0.26)))
        glyph_font.setBold(True)
        small_font = QFont("Segoe UI", 1)
        small_font.setPixelSize(max(7, int(unit * 0.155)))
        tiny_font = QFont("Segoe UI", 1)
        tiny_font.setPixelSize(max(6, int(unit * 0.14)))
        fm_small = QFontMetricsF(small_font)
        for k in self.layout_.keys:
            vis = self._visuals.get(k.id)
            if vis is None:
                continue
            self._paint_key(p, k, vis, unit, glyph_font, small_font, tiny_font, fm_small)

    def _paint_key(self, p, k, vis, unit, glyph_font, small_font, tiny_font, fm_small) -> None:
        path = self.key_path(k)
        rect = path.boundingRect()
        base = QColor(theme.ORIGIN_COLORS.get(vis.origin, theme.ORIGIN_COLORS["none"]))
        active_mod = k.id in MOD_KEY_LAYERS and self.layer in MOD_KEY_LAYERS[k.id]
        if active_mod:
            base = QColor(theme.ACCENT_DIM)
        if vis.fallback:
            base = QColor(base)
            base.setAlpha(120)
        if self.dim_unhighlighted and k.id not in self.highlight:
            base = QColor(base)
            base.setAlpha(55)
        if k.id == self.hover:
            base = base.lighter(125)
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, base.lighter(118))
        grad.setColorAt(1.0, base.darker(118))
        p.setBrush(QBrush(grad))
        if k.id == self.selected:
            pen = QPen(QColor(theme.ACCENT), max(2.0, unit * 0.05))
        elif k.id in self.highlight:
            pen = QPen(QColor(theme.YELLOW), max(2.0, unit * 0.05))
        else:
            pen = QPen(QColor(0, 0, 0, 110), 1.0)
            if vis.fallback:
                pen = QPen(QColor(255, 255, 255, 70), 1.0, Qt.DashLine)
        p.setPen(pen)
        p.drawPath(path)

        pad = unit * 0.09
        inner = rect.adjusted(pad, pad * 0.7, -pad, -pad * 0.7)
        if k.shape == "iso_enter":
            inner = QRectF(rect.left() + 0.25 * unit + pad, rect.top() + pad * 0.7,
                           rect.width() - 0.25 * unit - 2 * pad, rect.height() - 1.4 * pad)
        text_col = QColor(theme.TEXT)
        if vis.origin in ("none", "modifier") and not active_mod:
            text_col = QColor(theme.MUTED)
        if self.dim_unhighlighted and k.id not in self.highlight:
            text_col.setAlpha(90)
        # glyphe principal
        p.setFont(glyph_font if len(vis.glyph) <= 2 else small_font)
        p.setPen(text_col)
        glyph_rect = QRectF(inner.left(), inner.top(), inner.width(), unit * 0.34)
        p.drawText(glyph_rect, Qt.AlignLeft | Qt.AlignTop, vis.glyph)
        # caractères secondaires (Maj / AltGr) en petit sur la couche normale
        if k.kind in ("char", "dead") and self.layer == "none":
            p.setFont(tiny_font)
            p.setPen(QColor(theme.MUTED))
            sec = k.shift if k.shift and not (k.base and k.base.isalpha()) else ""
            if sec:
                p.drawText(glyph_rect, Qt.AlignRight | Qt.AlignTop, sec)
            if k.altgr:
                p.drawText(QRectF(inner.left(), inner.bottom() - unit * 0.2, inner.width(), unit * 0.2),
                           Qt.AlignRight | Qt.AlignBottom, k.altgr)
        # action
        if vis.action:
            p.setFont(small_font)
            col = QColor("white")
            if vis.fallback:
                col = QColor(theme.TEXT)
                col.setAlpha(170)
            if self.dim_unhighlighted and k.id not in self.highlight:
                col.setAlpha(80)
            p.setPen(col)
            area = QRectF(inner.left(), glyph_rect.bottom() - unit * 0.02, inner.width(),
                          inner.bottom() - glyph_rect.bottom() + unit * 0.02)
            if k.altgr and self.layer == "none":
                area.setRight(area.right() - unit * 0.12)
            lh = fm_small.lineSpacing()
            max_lines = max(1, int(area.height() // lh))
            text = ("↺ " if vis.fallback else "") + vis.action
            for i, line in enumerate(wrap_elide(text, fm_small, area.width(), max_lines)):
                p.drawText(QPointF(area.left(), area.top() + fm_small.ascent() + i * lh), line)

    # -- interactions ------------------------------------------------------
    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        k = self.key_at(ev.position())
        kid = k.id if k else None
        if kid != self.hover:
            self.hover = kid
            self.update()

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self.hover = None
        self.update()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            k = self.key_at(ev.position())
            if k is not None:
                self.selected = k.id
                self.update()
                self.keyClicked.emit(k.id)

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        k = self.key_at(ev.position())
        if k is not None:
            self.keyDoubleClicked.emit(k.id)

    def event(self, ev) -> bool:
        if ev.type() == QEvent.ToolTip:
            k = self.key_at(QPointF(ev.pos()))
            if k is None:
                QToolTip.hideText()
                return True
            vis = self._visuals.get(k.id)
            QToolTip.showText(ev.globalPos(), self._tooltip(k, vis), self)
            return True
        return super().event(ev)

    def _tooltip(self, k: PhysKey, vis: Optional[KeyVisual]) -> str:
        if vis is None:
            return k.label
        if vis.origin == "modifier":
            return f"<b>{k.label}</b><br>Touche de modification (non assignable seule)."
        lines = [f"<b>{vis.combo or k.label}</b>"]
        if vis.code is not None:
            lines.append(f"<span style='color:{theme.MUTED}'>Code FlightGear {vis.code}</span>")
        if vis.action:
            lines.append(vis.action)
            lines.append(f"<i>{theme.ORIGIN_LABELS.get(vis.origin, vis.origin)}</i>")
        else:
            lines.append(f"<i>Libre sur la couche {self.layer_name()}</i>")
        if vis.fallback:
            lines.append("↺ Aucune action spécifique : FlightGear se replie sur la même touche sans modificateur.")
        if vis.release_only:
            lines.append("Action déclenchée au relâchement uniquement.")
        if k.note:
            lines.append(f"<span style='color:{theme.MUTED}'>{k.note}</span>")
        return "<br>".join(lines)

    def layer_name(self) -> str:
        from ..core.layouts import LAYER_NAME

        return LAYER_NAME.get(self.layer, self.layer)


class Legend(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        for key in ("global", "aircraft", "disabled", "none"):
            lay.addWidget(self._chip(theme.ORIGIN_COLORS[key], theme.ORIGIN_LABELS[key]))
        fb = QColor(theme.ORIGIN_COLORS["global"])
        fb.setAlpha(120)
        lay.addWidget(self._chip(fb, "↺ Repli (touche sans modificateur)", dashed=True))
        lay.addStretch(1)

    def _chip(self, color: QColor, text: str, dashed: bool = False) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        sw = QLabel()
        sw.setFixedSize(16, 16)
        border = "1px dashed rgba(255,255,255,0.5)" if dashed else "1px solid rgba(0,0,0,0.4)"
        sw.setStyleSheet(f"background: rgba({color.red()},{color.green()},{color.blue()},{color.alpha()});"
                         f"border-radius: 3px; border: {border};")
        h.addWidget(sw)
        lbl = QLabel(text)
        lbl.setProperty("muted", True)
        h.addWidget(lbl)
        return w


def layer_mask(layer: str) -> int:
    return LAYER_MASK[layer]
