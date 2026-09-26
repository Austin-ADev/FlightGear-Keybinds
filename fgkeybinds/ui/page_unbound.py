"""Page « Non assignées » : actions sans raccourci et combinaisons libres."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.bindings import binding_from_xml, summarize
from ..core.catalog import Action
from ..core.keyboard import combo_label
from ..core.layouts import LAYERS
from ..core.search import fold
from . import ops, theme
from .capture import JoystickCaptureDialog, KeyCaptureDialog
from .state import AppState


class UnboundPage(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self._dirty = True
        self.action: Optional[Action] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        tabs = QTabWidget()
        root.addWidget(tabs)

        # --- actions ----------------------------------------------------------
        act = QWidget()
        al = QVBoxLayout(act)
        bar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrer les actions…")
        self.filter.setClearButtonEnabled(True)
        bar.addWidget(self.filter, 1)
        self.use_js = QCheckBox("Tenir compte des périphériques branchés")
        self.use_js.setChecked(True)
        bar.addWidget(self.use_js)
        self.show_all = QCheckBox("Afficher aussi les actions assignées")
        bar.addWidget(self.show_all)
        al.addLayout(bar)
        self.summary = QLabel()
        self.summary.setProperty("muted", True)
        al.addWidget(self.summary)
        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Action", "Type", "Assignée à"])
        self.tree.setColumnWidth(0, 330)
        self.tree.setColumnWidth(1, 70)
        split.addWidget(self.tree)
        card = QFrame()
        card.setProperty("card", True)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        self.a_title = QLabel("Sélectionnez une action")
        self.a_title.setProperty("heading", True)
        self.a_title.setWordWrap(True)
        cl.addWidget(self.a_title)
        self.a_info = QLabel()
        self.a_info.setWordWrap(True)
        self.a_info.setProperty("muted", True)
        self.a_info.setTextFormat(Qt.RichText)
        cl.addWidget(self.a_info)
        self.a_xml = QPlainTextEdit()
        self.a_xml.setReadOnly(True)
        self.a_xml.setFont(theme.mono_font(9))
        self.a_xml.setMaximumHeight(180)
        cl.addWidget(self.a_xml)
        self.btn_key = QPushButton("⌨  Assigner à une touche…")
        self.btn_key.setProperty("primary", True)
        self.btn_joy = QPushButton("🎮  Assigner à un périphérique…")
        cl.addWidget(self.btn_key)
        cl.addWidget(self.btn_joy)
        note = QLabel("Les actions du catalogue utilisent les propriétés génériques de FlightGear. Certains "
                      "aéronefs définissent leurs propres commandes (voir l'onglet Aéronefs).")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        cl.addWidget(note)
        cl.addStretch(1)
        split.addWidget(card)
        split.setSizes([700, 420])
        al.addWidget(split, 1)
        tabs.addTab(act, "Actions sans raccourci")

        # --- touches libres ---------------------------------------------------
        free = QWidget()
        fl = QVBoxLayout(free)
        self.free_info = QLabel()
        self.free_info.setProperty("muted", True)
        self.free_info.setWordWrap(True)
        fl.addWidget(self.free_info)
        self.free_tree = QTreeWidget()
        self.free_tree.setHeaderLabels(["Combinaison", "Touche physique"])
        self.free_tree.setColumnWidth(0, 260)
        fl.addWidget(self.free_tree, 1)
        tabs.addTab(free, "Combinaisons libres")

        self.filter.textChanged.connect(self._fill)
        self.use_js.toggled.connect(self._invalidate)
        self.show_all.toggled.connect(self._fill)
        self.tree.currentItemChanged.connect(self._pick)
        self.btn_key.clicked.connect(self._assign_key)
        self.btn_joy.clicked.connect(self._assign_joy)
        self.free_tree.itemDoubleClicked.connect(self._free_double)
        for sig in (state.contextChanged, state.dataChanged, state.devicesChanged, state.layoutChanged):
            sig.connect(self._invalidate)
        self._pick(None)

    def _invalidate(self) -> None:
        self._dirty = True
        if self.isVisible():
            self.refresh()

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        if self._dirty:
            self.refresh()

    def refresh(self) -> None:
        self._dirty = False
        self._compute_usage()
        self._fill()
        self._fill_free()

    # -- calcul ----------------------------------------------------------------
    def _compute_usage(self) -> None:
        ws = self.state.ws
        kb = self.state.keyboard
        self.usage: dict[str, list[str]] = {}
        for s in kb.slots():
            if not s.is_bound:
                continue
            nodes = [b.node for b in s.live_press + s.live_release]
            for a in ws.catalog.actions:
                if a.matches_any(nodes):
                    self.usage.setdefault(a.id, []).append(combo_label(s.code, s.mask))
        if self.use_js.isChecked():
            for aj in ws.active_joysticks():
                cfg = aj.config
                if cfg is None or aj.mode not in ("exact", "default"):
                    continue
                for ax in cfg.axes.values():
                    if ax.index < 8:
                        for a in ws.catalog.actions:
                            if a.matches_any(ax.bindings):
                                self.usage.setdefault(a.id, []).append(f"{aj.name} axe {ax.index}")
                for b in cfg.buttons.values():
                    if b.index < 32:
                        for a in ws.catalog.actions:
                            if a.matches_any(b.press + b.release):
                                self.usage.setdefault(a.id, []).append(f"{aj.name} bouton {b.index}")

    def _fill(self) -> None:
        ws = self.state.ws
        q = fold(self.filter.text().strip())
        cur = self.action.id if self.action else None
        self.tree.blockSignals(True)
        self.tree.clear()
        cats: dict[str, QTreeWidgetItem] = {}
        n_unbound = 0
        select = None
        for a in ws.catalog.actions:
            used = getattr(self, "usage", {}).get(a.id, [])
            if not used:
                n_unbound += 1
            if used and not self.show_all.isChecked():
                continue
            if q and q not in fold(a.label + " " + a.category + " " + a.id):
                continue
            cat = cats.get(a.category)
            if cat is None:
                cat = QTreeWidgetItem([a.category])
                cat.setFlags(cat.flags() & ~Qt.ItemIsSelectable)
                cat.setForeground(0, QColor(theme.MUTED))
                cats[a.category] = cat
                self.tree.addTopLevelItem(cat)
            it = QTreeWidgetItem([a.label, "Axe" if a.kind == "axis" else "Bouton", ", ".join(used) or "—"])
            it.setData(0, Qt.UserRole, a.id)
            if used:
                it.setForeground(0, QColor(theme.MUTED))
                it.setForeground(2, QColor(theme.GREEN))
            else:
                it.setForeground(2, QColor(theme.AMBER))
            cat.addChild(it)
            if a.id == cur:
                select = it
        for c in cats.values():
            c.setText(0, f"{c.text(0)}  ({c.childCount()})")
        self.tree.expandAll()
        self.tree.blockSignals(False)
        if select is not None:
            self.tree.setCurrentItem(select)
        total = len(ws.catalog.actions)
        where = "le clavier et les périphériques branchés" if self.use_js.isChecked() else "le clavier"
        self.summary.setText(f"Contexte : {ws.context_label(self.state.context)} — {n_unbound} action(s) sur "
                             f"{total} ne sont assignées nulle part ({where}).")

    def _fill_free(self) -> None:
        lay = self.state.layout
        kb = self.state.keyboard
        self.free_tree.clear()
        total = 0
        for lid, name, _ in LAYERS:
            if lid == "altgr" and not lay.has_altgr:
                continue
            grp = QTreeWidgetItem([name])
            grp.setForeground(0, QColor(theme.MUTED))
            seen = set()
            for k in lay.keys:
                if not k.bindable or k.kind == "dead":
                    continue
                ki = k.input_for(lid)
                if ki is None or (ki.code, ki.mask) in seen:
                    continue
                seen.add((ki.code, ki.mask))
                res = kb.resolve(ki.code, ki.mask)
                if res.slot is not None and (res.slot.is_bound or res.slot.is_disabled):
                    continue
                it = QTreeWidgetItem([combo_label(ki.code, ki.mask), f"{name} + {k.label or k.base}"
                                      if lid != "none" else (k.label or k.base or "")])
                it.setData(0, Qt.UserRole, (ki.code, ki.mask))
                grp.addChild(it)
            grp.setText(0, f"{name}  ({grp.childCount()})")
            total += grp.childCount()
            self.free_tree.addTopLevelItem(grp)
            grp.setExpanded(lid in ("none", "shift"))
        self.free_info.setText(
            f"{total} combinaison(s) sans aucune action (même par repli) sur le clavier {lay.name}, "
            f"dans le contexte « {self.state.ws.context_label(self.state.context)} ». "
            "Double-cliquez pour assigner une action.")

    # -- sélection / assignation -------------------------------------------
    def _pick(self, item: Optional[QTreeWidgetItem], _prev=None) -> None:
        aid = item.data(0, Qt.UserRole) if item is not None else None
        self.action = self.state.ws.catalog.by_id.get(aid) if aid else None
        a = self.action
        self.btn_key.setEnabled(a is not None and a.kind != "axis")
        self.btn_joy.setEnabled(a is not None)
        if a is None:
            self.a_title.setText("Sélectionnez une action")
            self.a_info.setText("Choisissez une action pour l'assigner à une touche ou à une commande de "
                                "périphérique.")
            self.a_xml.setPlainText("")
            return
        self.a_title.setText(a.label)
        lines = [f"Catégorie : {a.category}", "Type : " + ("axe analogique" if a.kind == "axis" else "bouton / touche")]
        for x in a.press:
            lines.append("À l'appui : " + summarize(binding_from_xml(x)))
        for x in a.release:
            lines.append("Au relâchement : " + summarize(binding_from_xml(x)))
        used = getattr(self, "usage", {}).get(a.id, [])
        if used:
            lines.append(f"<span style='color:{theme.GREEN}'>Déjà assignée à : {', '.join(used)}</span>")
        if a.kind == "axis":
            lines.append("Une action d'axe ne peut être assignée qu'à un axe de périphérique.")
        self.a_info.setText("<br>".join(lines))
        self.a_xml.setPlainText("\n".join(a.press + ([
            "<!-- relâchement -->"] + a.release if a.release else [])))

    def _assign_key(self) -> None:
        a = self.action
        if a is None:
            return
        dlg = KeyCaptureDialog(self, self.state.layout, self.state.keyboard, f"Assigner « {a.label} »",
                               "La combinaison choisie recevra cette action dans le contexte "
                               f"« {self.state.ws.context_label(self.state.context)} ».")
        if dlg.exec() and dlg.result_combo:
            code, mask = dlg.result_combo
            ops.edit_key(self, self.state, code, mask, preset=a)

    def _assign_joy(self) -> None:
        a = self.action
        if a is None:
            return
        ws = self.state.ws
        devs = ws.devices
        if not devs:
            ops.error(self, Exception("Aucun périphérique branché. Branchez-le puis cliquez sur « Détecter » "
                                      "dans l'onglet Périphériques."))
            return
        dlg = JoystickCaptureDialog(self, devs, "axis" if a.kind == "axis" else "button")
        if not (dlg.exec() and dlg.result_control):
            return
        dev, typ, idx = dlg.result_control
        cfg, _mode = ws.joy_lib.match(dev.name)
        if cfg is None:
            try:
                ws.joystick_for_device(dev.name)
            except Exception as e:  # noqa: BLE001
                ops.error(self, e)
                return
            cfg, _mode = ws.joy_lib.match(dev.name)
        ops.edit_joystick_control(self, self.state, cfg, dev.name, typ, idx, preset=a)

    def _free_double(self, item: QTreeWidgetItem, _col: int) -> None:
        d = item.data(0, Qt.UserRole)
        if d:
            ops.edit_key(self, self.state, d[0], d[1])
