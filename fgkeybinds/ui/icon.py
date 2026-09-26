"""Icône de l'application dessinée par programme."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap


def render(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 64.0
    # touche de clavier
    cap = QRectF(4 * s, 6 * s, 56 * s, 52 * s)
    g = QLinearGradient(cap.topLeft(), cap.bottomLeft())
    g.setColorAt(0, QColor("#3d8fd6"))
    g.setColorAt(1, QColor("#1c4f82"))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#0d2740"))
    p.drawRoundedRect(cap.adjusted(0, 3 * s, 0, 3 * s), 11 * s, 11 * s)
    p.setBrush(g)
    p.drawRoundedRect(cap, 11 * s, 11 * s)
    # avion stylisé
    plane = QPainterPath()
    cx, cy = 32 * s, 31 * s
    plane.moveTo(cx, cy - 18 * s)
    plane.cubicTo(cx + 3 * s, cy - 18 * s, cx + 3 * s, cy - 12 * s, cx + 3 * s, cy - 8 * s)
    plane.lineTo(cx + 20 * s, cy + 2 * s)
    plane.lineTo(cx + 20 * s, cy + 6 * s)
    plane.lineTo(cx + 3 * s, cy + 1 * s)
    plane.lineTo(cx + 2.5 * s, cy + 11 * s)
    plane.lineTo(cx + 8 * s, cy + 15 * s)
    plane.lineTo(cx + 8 * s, cy + 18 * s)
    plane.lineTo(cx, cy + 16 * s)
    plane.lineTo(cx - 8 * s, cy + 18 * s)
    plane.lineTo(cx - 8 * s, cy + 15 * s)
    plane.lineTo(cx - 2.5 * s, cy + 11 * s)
    plane.lineTo(cx - 3 * s, cy + 1 * s)
    plane.lineTo(cx - 20 * s, cy + 6 * s)
    plane.lineTo(cx - 20 * s, cy + 2 * s)
    plane.lineTo(cx - 3 * s, cy - 8 * s)
    plane.cubicTo(cx - 3 * s, cy - 12 * s, cx - 3 * s, cy - 18 * s, cx, cy - 18 * s)
    p.setBrush(QColor("#f4f7fb"))
    p.drawPath(plane)
    p.setBrush(QColor("#f0a53a"))
    p.drawEllipse(QPointF(cx, cy - 12 * s), 1.6 * s, 1.6 * s)
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(render(sz))
    return icon
