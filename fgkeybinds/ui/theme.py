"""Thème sombre « cockpit » de l'application."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

BG = "#12161c"
PANEL = "#1a2029"
CARD = "#212833"
CARD_HI = "#29313d"
BORDER = "#323c4a"
TEXT = "#e4e8ee"
MUTED = "#8d99a8"
ACCENT = "#46b0ff"
ACCENT_DIM = "#2b6ea3"
AMBER = "#f0a53a"
GREEN = "#5bd67a"
RED = "#e26060"
YELLOW = "#f5d547"

# Couleurs par origine de binding
ORIGIN_COLORS = {
    "global": QColor("#2f6fc4"),
    "aircraft": QColor("#d98a1f"),
    "joystick": QColor("#2f9e8f"),
    "disabled": QColor("#9c3f3f"),
    "none": QColor("#262e39"),
    "modifier": QColor("#1a2029"),
}
ORIGIN_LABELS = {
    "global": "Global (FlightGear)",
    "aircraft": "Propre à l'aéronef",
    "joystick": "Périphérique",
    "disabled": "Désactivé par l'aéronef",
    "none": "Libre",
}

QSS = f"""
QWidget {{
    color: {TEXT};
    font-size: 10pt;
}}
QMainWindow, QDialog {{
    background: {BG};
}}
QToolTip {{
    background: {CARD_HI};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    top: -1px;
    background: {PANEL};
}}
QTabBar::tab {{
    background: transparent;
    color: {MUTED};
    padding: 9px 18px;
    margin-right: 2px;
    border: 1px solid transparent;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    background: {PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-bottom-color: {PANEL};
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT};
}}
QToolBar {{
    background: {PANEL};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    spacing: 8px;
}}
QStatusBar {{
    background: {PANEL};
    color: {MUTED};
    border-top: 1px solid {BORDER};
}}
QPushButton, QToolButton {{
    background: {CARD_HI};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 6px 12px;
}}
QPushButton:hover, QToolButton:hover {{
    border-color: {ACCENT_DIM};
    background: #303a48;
}}
QPushButton:pressed, QToolButton:pressed {{
    background: {ACCENT_DIM};
}}
QPushButton:checked, QToolButton:checked {{
    background: {ACCENT_DIM};
    border-color: {ACCENT};
    color: white;
}}
QPushButton:disabled, QToolButton:disabled {{
    color: #5d6875;
    background: {CARD};
}}
QPushButton[primary="true"] {{
    background: {ACCENT_DIM};
    border-color: {ACCENT};
    color: white;
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{
    background: #3584c2;
}}
QPushButton[primary="true"]:disabled, QPushButton[danger="true"]:disabled {{
    background: {CARD};
    border-color: {BORDER};
    color: #5d6875;
}}
QPushButton[danger="true"] {{
    background: #5a2a2a;
    border-color: #8a3a3a;
}}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 5px 7px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
}}
QTreeView, QTableView, QListView, QTreeWidget, QTableWidget, QListWidget {{
    background: {BG};
    alternate-background-color: #161b22;
    border: 1px solid {BORDER};
    border-radius: 5px;
    gridline-color: {BORDER};
    selection-background-color: {ACCENT_DIM};
    selection-color: white;
}}
QHeaderView::section {{
    background: {CARD};
    color: {MUTED};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    font-weight: 600;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 11px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0; height: 0;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {MUTED};
}}
QSplitter::handle {{
    background: {BORDER};
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: {BORDER};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT_DIM};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid #5d6875;
    border-radius: 3px;
    background: {BG};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: url(:/fgkb/check.svg);
}}
QCheckBox::indicator:disabled {{
    border-color: {BORDER};
    background: {CARD};
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
}}
QLabel[muted="true"] {{
    color: {MUTED};
}}
QLabel[heading="true"] {{
    font-size: 14pt;
    font-weight: 700;
}}
QLabel[badge="true"] {{
    border-radius: 4px;
    padding: 2px 8px;
    font-weight: 600;
}}
QFrame[card="true"] {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QMenu {{
    background: {CARD};
    border: 1px solid {BORDER};
}}
QMenu::item:selected {{
    background: {ACCENT_DIM};
}}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(BG))
    pal.setColor(QPalette.AlternateBase, QColor("#161b22"))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(CARD_HI))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT_DIM))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ToolTipBase, QColor(CARD_HI))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(MUTED))
    pal.setColor(QPalette.Link, QColor(ACCENT))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#5d6875"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5d6875"))
    app.setPalette(pal)
    f = QFont("Segoe UI", 10)
    app.setFont(f)
    app.setStyleSheet(QSS.replace(":/fgkb/check.svg", _check_svg()))


_CHECK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
    '<path d="M3.2 8.4 L6.6 11.6 L12.8 4.6" fill="none" stroke="white" stroke-width="2.2" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def _check_svg() -> str:
    """Écrit l'icône de case cochée dans le dossier de l'application (utilisée par la feuille de style)."""
    from ..core.settings import app_dir

    p = app_dir() / "check.svg"
    try:
        if not p.exists() or p.read_text(encoding="utf-8") != _CHECK_SVG:
            p.write_text(_CHECK_SVG, encoding="utf-8")
    except OSError:
        return ""
    return p.as_posix()


def mono_font(size: int = 10) -> QFont:
    f = QFont("Cascadia Mono")
    if not f.exactMatch():
        f = QFont("Consolas")
    f.setPointSize(size)
    f.setStyleHint(QFont.Monospace)
    return f
