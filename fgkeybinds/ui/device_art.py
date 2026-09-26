"""Illustrations vectorielles simples des types de périphériques."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import theme


class DeviceArt(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.kind = "stick"
        self.active = False
        self.setFixedSize(150, 150)

    def set_kind(self, kind: str, active: bool = False) -> None:
        self.kind = kind
        self.active = active
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.BG))
        p.drawRoundedRect(r, 14, 14)
        body = QLinearGradient(r.topLeft(), r.bottomLeft())
        body.setColorAt(0, QColor("#4a5566"))
        body.setColorAt(1, QColor("#262d38"))
        accent = QColor(theme.GREEN if self.active else theme.ACCENT)
        pen = QPen(QColor("#0b0e12"), 2)
        p.setPen(pen)
        p.setBrush(body)
        getattr(self, f"_draw_{self.kind}", self._draw_stick)(p, r, accent)

    # -- dessins ----------------------------------------------------------
    def _draw_stick(self, p: QPainter, r: QRectF, accent: QColor) -> None:
        cx = r.center().x()
        base = QRectF(cx - 45, r.bottom() - 34, 90, 24)
        p.drawRoundedRect(base, 10, 10)
        shaft = QPainterPath()
        shaft.moveTo(cx - 7, r.bottom() - 32)
        shaft.lineTo(cx - 9, r.top() + 58)
        shaft.lineTo(cx + 9, r.top() + 58)
        shaft.lineTo(cx + 7, r.bottom() - 32)
        shaft.closeSubpath()
        p.drawPath(shaft)
        grip = QPainterPath()
        grip.addRoundedRect(QRectF(cx - 16, r.top() + 14, 32, 52), 13, 13)
        p.drawPath(grip)
        p.setBrush(accent)
        p.drawEllipse(QPointF(cx, r.top() + 24), 5, 5)  # chapeau chinois
        p.drawRoundedRect(QRectF(cx - 20, r.top() + 38, 7, 12), 3, 3)  # gâchette

    def _draw_throttle(self, p: QPainter, r: QRectF, accent: QColor) -> None:
        base = QRectF(r.left() + 16, r.bottom() - 44, r.width() - 32, 34)
        p.drawRoundedRect(base, 8, 8)
        slot = QRectF(r.left() + 30, r.bottom() - 36, r.width() - 60, 6)
        p.setBrush(QColor("#0b0e12"))
        p.drawRoundedRect(slot, 3, 3)
        p.setBrush(QColor("#3a4452"))
        lever = QPainterPath()
        lever.moveTo(r.center().x() - 4, r.bottom() - 36)
        lever.lineTo(r.center().x() - 22, r.top() + 44)
        lever.lineTo(r.center().x() - 8, r.top() + 44)
        lever.lineTo(r.center().x() + 6, r.bottom() - 36)
        lever.closeSubpath()
        p.drawPath(lever)
        p.setBrush(QColor("#4a5566"))
        p.drawRoundedRect(QRectF(r.center().x() - 42, r.top() + 18, 50, 30), 10, 10)
        p.setBrush(accent)
        p.drawEllipse(QPointF(r.center().x() - 26, r.top() + 30), 4, 4)
        p.drawEllipse(QPointF(r.center().x() - 12, r.top() + 30), 4, 4)

    def _draw_yoke(self, p: QPainter, r: QRectF, accent: QColor) -> None:
        cx, cy = r.center().x(), r.center().y() - 8
        p.drawRoundedRect(QRectF(cx - 8, cy, 16, r.bottom() - cy - 8), 4, 4)
        wheel = QPainterPath()
        wheel.moveTo(cx - 58, cy - 26)
        wheel.quadTo(cx - 60, cy + 22, cx - 38, cy + 24)
        wheel.lineTo(cx + 38, cy + 24)
        wheel.quadTo(cx + 60, cy + 22, cx + 58, cy - 26)
        wheel.lineTo(cx + 40, cy - 26)
        wheel.quadTo(cx + 40, cy + 6, cx + 26, cy + 8)
        wheel.lineTo(cx - 26, cy + 8)
        wheel.quadTo(cx - 40, cy + 6, cx - 40, cy - 26)
        wheel.closeSubpath()
        p.drawPath(wheel)
        p.setBrush(accent)
        p.drawEllipse(QPointF(cx - 49, cy - 18), 4, 4)
        p.drawEllipse(QPointF(cx + 49, cy - 18), 4, 4)

    def _draw_pedals(self, p: QPainter, r: QRectF, accent: QColor) -> None:
        p.drawRoundedRect(QRectF(r.left() + 12, r.bottom() - 30, r.width() - 24, 18), 6, 6)
        for dx, tilt in ((-30, -8), (30, 8)):
            cx = r.center().x() + dx
            ped = QPainterPath()
            ped.moveTo(cx - 17 + tilt / 2, r.top() + 22)
            ped.lineTo(cx + 17 + tilt / 2, r.top() + 22)
            ped.lineTo(cx + 19 - tilt / 2, r.bottom() - 34)
            ped.lineTo(cx - 19 - tilt / 2, r.bottom() - 34)
            ped.closeSubpath()
            p.drawPath(ped)
            p.save()
            p.setPen(QPen(accent, 2))
            for i in range(4):
                y = r.top() + 38 + i * 16
                p.drawLine(QPointF(cx - 10, y), QPointF(cx + 10, y))
            p.restore()

    def _draw_gamepad(self, p: QPainter, r: QRectF, accent: QColor) -> None:
        cx, cy = r.center().x(), r.center().y()
        pad = QPainterPath()
        pad.moveTo(cx - 40, cy - 22)
        pad.lineTo(cx + 40, cy - 22)
        pad.cubicTo(cx + 70, cy - 22, cx + 72, cy + 34, cx + 52, cy + 34)
        pad.cubicTo(cx + 38, cy + 34, cx + 32, cy + 12, cx + 20, cy + 12)
        pad.lineTo(cx - 20, cy + 12)
        pad.cubicTo(cx - 32, cy + 12, cx - 38, cy + 34, cx - 52, cy + 34)
        pad.cubicTo(cx - 72, cy + 34, cx - 70, cy - 22, cx - 40, cy - 22)
        p.drawPath(pad)
        p.setBrush(accent)
        for dx, dy in ((30, -8), (40, 2), (30, 12), (20, 2)):
            p.drawEllipse(QPointF(cx + dx, cy + dy - 4), 4, 4)
        p.drawRect(QRectF(cx - 44, cy - 6, 22, 6))
        p.drawRect(QRectF(cx - 36, cy - 14, 6, 22))
