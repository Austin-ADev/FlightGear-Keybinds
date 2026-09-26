"""Éditeur de courbe de sensibilité d'un axe (zone morte, expo, inversion)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..core import joystick as js
from ..core.curves import AxisCurve
from . import theme


class CurveWidget(QWidget):
    """Tracé entrée → sortie d'un axe."""

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self.curve = AxisCurve()
        self.live: Optional[float] = None
        self.compact = compact
        self.setMinimumSize(60 if compact else 320, 60 if compact else 320)

    def set_curve(self, c: AxisCurve) -> None:
        self.curve = c
        self.update()

    def set_live(self, v: Optional[float]) -> None:
        self.live = v
        self.update()

    def _plot_rect(self) -> QRectF:
        m = 4 if self.compact else 34
        side = min(self.width(), self.height()) - 2 * m
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot_rect()
        p.fillRect(self.rect(), QColor(theme.BG if not self.compact else theme.CARD))
        p.fillRect(r, QColor("#0e1217"))

        def pt(x: float, y: float) -> QPointF:
            return QPointF(r.left() + (x + 1) / 2 * r.width(), r.bottom() - (y + 1) / 2 * r.height())

        # grille
        p.setPen(QPen(QColor(theme.BORDER), 1))
        steps = 4 if self.compact else 8
        for i in range(steps + 1):
            v = -1 + 2 * i / steps
            p.drawLine(pt(v, -1), pt(v, 1))
            p.drawLine(pt(-1, v), pt(1, v))
        p.setPen(QPen(QColor(theme.MUTED), 1.2))
        p.drawLine(pt(-1, 0), pt(1, 0))
        p.drawLine(pt(0, -1), pt(0, 1))
        # zone morte
        db = self.curve.dead_band
        if db > 0:
            band = QRectF(pt(-db, 1), pt(db, -1))
            c = QColor(theme.AMBER)
            c.setAlpha(45)
            p.fillRect(band, c)
        # référence linéaire
        ref = QPen(QColor(theme.MUTED), 1, Qt.DashLine)
        p.setPen(ref)
        sgn = -1.0 if self.curve.invert else 1.0
        p.drawLine(pt(-1, -sgn), pt(1, sgn))
        # courbe
        path = QPainterPath()
        n = 160
        for i in range(n + 1):
            x = -1 + 2 * i / n
            y = max(-1.0, min(1.0, self.curve.shaped(x)))
            if i == 0:
                path.moveTo(pt(x, y))
            else:
                path.lineTo(pt(x, y))
        p.setPen(QPen(QColor(theme.ACCENT), 2.4 if not self.compact else 1.6))
        p.drawPath(path)
        # position en direct
        if self.live is not None:
            x = max(-1.0, min(1.0, self.live))
            y = max(-1.0, min(1.0, self.curve.shaped(x)))
            p.setPen(QPen(QColor(theme.GREEN), 1, Qt.DotLine))
            p.drawLine(pt(x, -1), pt(x, 1))
            p.setBrush(QColor(theme.GREEN))
            p.setPen(Qt.NoPen)
            p.drawEllipse(pt(x, y), 5 if not self.compact else 3, 5 if not self.compact else 3)
        if not self.compact:
            p.setPen(QColor(theme.MUTED))
            f = QFont("Segoe UI", 8)
            p.setFont(f)
            p.drawText(QRectF(r.left(), r.bottom() + 4, r.width(), 16), Qt.AlignCenter, "Entrée (position physique)")
            p.save()
            p.translate(r.left() - 20, r.center().y())
            p.rotate(-90)
            p.drawText(QRectF(-r.height() / 2, -8, r.height(), 16), Qt.AlignCenter, "Sortie transmise")
            p.restore()
            for v, lbl in ((-1, "−1"), (0, "0"), (1, "+1")):
                p.drawText(QRectF(pt(v, -1).x() - 12, r.bottom() + 16, 24, 14), Qt.AlignCenter, lbl)


class CurveDialog(QDialog):
    def __init__(self, parent, title: str, curve: AxisCurve, device: Optional[js.Device], axis_index: int,
                 note: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 520)
        self.device = device
        self.axis_index = axis_index
        self.curve = AxisCurve(**curve.__dict__)
        root = QVBoxLayout(self)
        h = QLabel(title)
        h.setProperty("heading", True)
        root.addWidget(h)
        body = QHBoxLayout()
        root.addLayout(body, 1)
        self.plot = CurveWidget()
        body.addWidget(self.plot, 3)
        side = QVBoxLayout()
        body.addLayout(side, 2)
        form = QFormLayout()
        self.db_slider, self.db_spin = self._slider_pair(0, 50, curve.dead_band * 100, "%")
        self.ex_slider, self.ex_spin = self._slider_pair(0, 100, curve.expo * 100, "%")
        form.addRow("Zone morte", self._row(self.db_slider, self.db_spin))
        form.addRow("Expo", self._row(self.ex_slider, self.ex_spin))
        self.invert = QCheckBox("Inverser le sens de l'axe")
        self.invert.setChecked(curve.invert)
        form.addRow("", self.invert)
        side.addLayout(form)
        expl = QLabel(
            "<b>Zone morte</b> : ignore les petits mouvements autour du centre (paramètre natif "
            "<i>dead-band</i> de FlightGear ; le reste de la course est redimensionné).<br><br>"
            "<b>Expo</b> : adoucit le centre pour plus de précision, sans réduire le débattement total "
            "(<i>sortie = (1−e)·x + e·x³</i>, implémenté en Nasal dans le binding de l'axe).")
        expl.setWordWrap(True)
        expl.setProperty("muted", True)
        expl.setTextFormat(Qt.RichText)
        side.addWidget(expl)
        info = []
        if curve.kind == "scale":
            info.append(f"Propriété pilotée : <b>{curve.prop}</b>")
            if curve.power > 1:
                info.append(f"Puissance d'origine conservée : x<sup>{curve.power}</sup>")
            if curve.offset or abs(curve.factor) != 1.0:
                info.append(f"Décalage {curve.offset:g}, facteur {abs(curve.factor):g}")
        elif curve.kind == "nasal":
            info.append("Binding Nasal : la courbe est appliquée avant le script.")
        else:
            info.append("<span style='color:%s'>Cet axe n'a pas encore d'action.</span>" % theme.AMBER)
        if note:
            info.append(note)
        il = QLabel("<br>".join(info))
        il.setWordWrap(True)
        il.setTextFormat(Qt.RichText)
        side.addWidget(il)
        self.live_lbl = QLabel("")
        self.live_lbl.setProperty("muted", True)
        side.addWidget(self.live_lbl)
        side.addStretch(1)
        bb = QDialogButtonBox()
        reset = bb.addButton("Linéaire", QDialogButtonBox.ResetRole)
        ok = bb.addButton("Appliquer", QDialogButtonBox.AcceptRole)
        ok.setProperty("primary", True)
        bb.addButton("Annuler", QDialogButtonBox.RejectRole)
        root.addWidget(bb)
        reset.clicked.connect(self._reset)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        for w in (self.db_spin, self.ex_spin):
            w.valueChanged.connect(self._changed)
        self.invert.toggled.connect(self._changed)
        self._changed()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        if device is not None:
            self.timer.start(30)
        else:
            self.live_lbl.setText("Branchez le périphérique pour voir la position en direct.")

    def _slider_pair(self, lo: int, hi: int, val: float, suffix: str):
        s = QSlider(Qt.Horizontal)
        s.setRange(lo * 10, hi * 10)
        s.setValue(int(round(val * 10)))
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(1)
        sp.setSuffix(" " + suffix)
        sp.setValue(val)
        sp.setFixedWidth(90)
        s.valueChanged.connect(lambda v: sp.setValue(v / 10))
        sp.valueChanged.connect(lambda v: s.setValue(int(round(v * 10))))
        return s, sp

    def _row(self, a: QWidget, b: QWidget) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(a, 1)
        h.addWidget(b)
        return w

    def _changed(self, *args) -> None:
        self.curve.dead_band = self.db_spin.value() / 100
        self.curve.expo = self.ex_spin.value() / 100
        self.curve.invert = self.invert.isChecked()
        self.plot.set_curve(self.curve)

    def _reset(self) -> None:
        self.db_spin.setValue(0)
        self.ex_spin.setValue(0)

    def _poll(self) -> None:
        st = self.device.poll() if self.device else None
        if st is None or self.axis_index >= len(st.axes):
            self.plot.set_live(None)
            return
        v = st.axes[self.axis_index]
        self.plot.set_live(v)
        self.live_lbl.setText(f"Position : {v:+.3f}  →  sortie {self.curve.shaped(v):+.3f}")

    def values(self) -> tuple[float, float, bool]:
        return self.curve.dead_band, self.curve.expo, self.curve.invert

    def done(self, r: int) -> None:
        self.timer.stop()
        super().done(r)
