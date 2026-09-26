"""Page « Recherche » : par touche ou par action."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import search as srch
from ..core.keyboard import combo_label
from . import theme
from .capture import KeyCaptureDialog
from .state import AppState


class SearchPage(QWidget):
    goKeyboard = Signal()
    goDevices = Signal()

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self._items: list[srch.SearchItem] = []
        self._dirty = True

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        bar = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Rechercher une action (« train », « volets », « /controls/flight »…) "
                                      "ou une touche (« ctrl+a », « maj+F1 », « g »)")
        self.query.setClearButtonEnabled(True)
        self.query.setMinimumHeight(34)
        bar.addWidget(self.query, 1)
        self.mode = QComboBox()
        self.mode.addItem("Tout", "all")
        self.mode.addItem("Par touche", "key")
        self.mode.addItem("Par action", "action")
        bar.addWidget(self.mode)
        self.btn_capture = QPushButton("⌨  Capturer une touche…")
        bar.addWidget(self.btn_capture)
        root.addLayout(bar)
        opt = QHBoxLayout()
        self.all_js = QCheckBox("Inclure toutes les configurations de joysticks de la bibliothèque")
        self.all_js.setChecked(state.settings.search_all_joysticks)
        opt.addWidget(self.all_js)
        opt.addStretch(1)
        self.count = QLabel()
        self.count.setProperty("muted", True)
        opt.addWidget(self.count)
        root.addLayout(opt)
        self.keyinfo = QLabel()
        self.keyinfo.setWordWrap(True)
        self.keyinfo.setTextFormat(Qt.RichText)
        self.keyinfo.setVisible(False)
        self.keyinfo.setStyleSheet(f"background: {theme.CARD}; border: 1px solid {theme.BORDER};"
                                   f" border-radius: 6px; padding: 10px;")
        root.addWidget(self.keyinfo)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Périphérique", "Entrée", "Action", "Détail", "Origine"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Interactive)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 230)
        self.table.setColumnWidth(2, 330)
        root.addWidget(self.table, 1)
        hint = QLabel("Double-cliquez sur un résultat pour l'afficher sur le clavier ou le périphérique.")
        hint.setProperty("muted", True)
        root.addWidget(hint)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self.run)
        self.query.textChanged.connect(lambda: self._debounce.start())
        self.mode.currentIndexChanged.connect(self.run)
        self.all_js.toggled.connect(self._toggle_all)
        self.btn_capture.clicked.connect(self._capture)
        self.table.cellDoubleClicked.connect(self._open)
        for sig in (state.contextChanged, state.dataChanged, state.devicesChanged, state.layoutChanged):
            sig.connect(self._invalidate)

    def _toggle_all(self, on: bool) -> None:
        self.state.settings.search_all_joysticks = on
        self.state.settings.save()
        self._invalidate()

    def _invalidate(self) -> None:
        self._dirty = True
        if self.isVisible():
            self.run()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self._dirty:
            self.run()

    def _build(self) -> None:
        ws = self.state.ws
        ctx_name = "Clavier" if self.state.context.is_global else "Clavier (" + ws.context_label(self.state.context) + ")"
        items = srch.keyboard_items(self.state.keyboard, self.state.layout, ctx_name, ws.catalog)
        seen = set()
        for aj in ws.active_joysticks():
            if aj.config is not None and aj.mode in ("exact", "default"):
                items += srch.joystick_items(aj.config, aj.device.name, ws.catalog)
                seen.add(aj.config.path)
        if self.all_js.isChecked():
            for cfg in ws.joy_lib.configs:
                if cfg.path not in seen:
                    items += srch.joystick_items(cfg, None, ws.catalog)
        self._items = items
        self._dirty = False

    def run(self) -> None:
        if self._dirty:
            self._build()
        q = self.query.text().strip()
        mode = self.mode.currentData()
        combo = srch.parse_combo(q) if q and mode in ("all", "key") else None
        results: list[srch.SearchItem] = []
        self.keyinfo.setVisible(False)
        if combo is not None:
            results += self._key_results(*combo)
        if mode in ("all", "action") or (mode == "key" and combo is None and q):
            if mode == "key":
                results += [it for it in srch.text_filter(self._items, q) if fold_in(q, it.input)]
            else:
                txt = [it for it in srch.text_filter(self._items, q) if it not in results]
                results += txt
        if not q:
            results = list(self._items)
        self._fill(results)

    def _key_results(self, code: int, mask: int) -> list[srch.SearchItem]:
        kb = self.state.keyboard
        res = kb.resolve(code, mask)
        combo = combo_label(code, mask)
        hint = srch.physical_hint(self.state.layout, code, mask)
        where = f" — sur votre clavier {self.state.layout.name} : <b>{hint}</b>" if hint else ""
        if res.slot is not None and res.slot.is_bound:
            pre = (f"par repli sur {combo_label(code, res.used_mask)} : " if res.fallback else "")
            txt = f"<b>{combo}</b>{where}<br>Déclenche {pre}<b>{res.slot.description()}</b>"
        else:
            txt = f"<b>{combo}</b>{where}<br><span style='color:{theme.GREEN}'>Aucune action : combinaison libre.</span>"
        self.keyinfo.setText(txt)
        self.keyinfo.setVisible(True)
        out = []
        for it in self._items:
            ref = it.ref
            if ref.get("type") == "key" and ref.get("code") == code:
                out.append(it)
        # la combinaison exacte en premier
        out.sort(key=lambda it: (it.ref.get("mask") != res.used_mask, it.ref.get("mask", 0)))
        return out

    def _fill(self, items: list[srch.SearchItem]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(items))
        for r, it in enumerate(items):
            vals = [it.context, it.input, it.action, it.detail,
                    theme.ORIGIN_LABELS.get(it.origin, it.origin)]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                cell.setToolTip(v)
                if c == 0:
                    cell.setData(Qt.UserRole, it.ref)
                if c == 4:
                    col = theme.ORIGIN_COLORS.get(it.origin)
                    if col is not None:
                        cell.setForeground(QColor(col).lighter(150))
                if c == 3:
                    cell.setForeground(QColor(theme.MUTED))
                self.table.setItem(r, c, cell)
        self.table.setSortingEnabled(True)
        self.count.setText(f"{len(items)} résultat(s)")

    def _capture(self) -> None:
        dlg = KeyCaptureDialog(self, self.state.layout, self.state.keyboard, "Rechercher une touche")
        if dlg.exec() and dlg.result_combo:
            code, mask = dlg.result_combo
            self.mode.setCurrentIndex(self.mode.findData("key"))
            self.query.setText(combo_label(code, mask))
            self.run()

    def _open(self, row: int, _col: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        ref = item.data(Qt.UserRole) or {}
        if ref.get("type") == "key":
            self.goKeyboard.emit()
            self.state.navigateKey.emit(ref["code"], ref["mask"])
        elif ref.get("type") in ("axis", "button"):
            self.goDevices.emit()
            self.state.navigateControl.emit(ref["config"], ref["type"], ref["index"], ref.get("device") or "")


def fold_in(q: str, s: str) -> bool:
    return srch.fold(q) in srch.fold(s)
