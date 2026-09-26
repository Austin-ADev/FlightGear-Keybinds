"""Page « Clavier » : visualisation et édition des touches."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.keyboard import combo_label
from ..core.layouts import LAYER_NAME, LAYERS, MODIFIER_KEY_IDS, PhysKey, live_layer, scancode_map
from . import ops, theme
from .capture import event_to_fg
from .keyboard_widget import KeyboardWidget, Legend
from .state import AppState


class KeyboardPage(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.layer = "none"  # couche choisie par l'utilisateur
        self.shown_layer = "none"  # couche affichée (peut suivre les modificateurs tenus)
        self.current_key: Optional[PhysKey] = None
        self.held: set[str] = set()  # touches physiques enfoncées
        self.scanmap: dict[int, str] = scancode_map(state.layout)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        top = QHBoxLayout()
        lbl = QLabel("Modificateurs :")
        lbl.setProperty("muted", True)
        top.addWidget(lbl)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.layer_buttons: dict[str, QPushButton] = {}
        for lid, name, _ in LAYERS:
            b = QPushButton(name)
            b.setCheckable(True)
            b.setMinimumWidth(70)
            self.group.addButton(b)
            self.layer_buttons[lid] = b
            top.addWidget(b)
            b.clicked.connect(lambda _=False, l=lid: self.set_layer(l))
        self.layer_buttons["none"].setChecked(True)
        top.addStretch(1)
        self.ctx_label = QLabel()
        self.ctx_label.setProperty("muted", True)
        top.addWidget(self.ctx_label)
        root.addLayout(top)
        leg = QHBoxLayout()
        leg.addWidget(Legend(), 1)
        self.live = QCheckBox("Illuminer les touches pressées")
        self.live.setToolTip("Quand cet onglet est affiché, les touches frappées au clavier s'illuminent et "
                             "leur action s'affiche. Les modificateurs tenus (Maj, Ctrl, Alt, AltGr) "
                             "affichent la couche correspondante.")
        self.live.setChecked(state.settings.live_keys)
        leg.addWidget(self.live)
        root.addLayout(leg)
        self.banner = QLabel()
        self.banner.setTextFormat(Qt.RichText)
        self.banner.setStyleSheet(f"background: {theme.CARD}; border: 1px solid {theme.BORDER};"
                                  f" border-radius: 6px; padding: 7px 12px;")
        root.addWidget(self.banner)

        split = QSplitter(Qt.Vertical)
        self.kbw = KeyboardWidget()
        split.addWidget(self.kbw)

        # panneau de détail
        detail = QFrame()
        detail.setProperty("card", True)
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(14, 10, 14, 10)
        head = QHBoxLayout()
        self.key_title = QLabel("Cliquez sur une touche")
        self.key_title.setProperty("heading", True)
        head.addWidget(self.key_title)
        self.key_info = QLabel("")
        self.key_info.setProperty("muted", True)
        head.addWidget(self.key_info, 1)
        self.btn_edit = QPushButton("Modifier…")
        self.btn_edit.setProperty("primary", True)
        self.btn_clear = QPushButton("Effacer")
        self.btn_restore = QPushButton("Rétablir l'action globale")
        for b in (self.btn_edit, self.btn_clear, self.btn_restore):
            head.addWidget(b)
        dl.addLayout(head)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Couche", "Combinaison", "Action", "Origine", "Code"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        dl.addWidget(self.table)
        split.addWidget(detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([460, 280])
        root.addWidget(split, 1)

        self.kbw.keyClicked.connect(self._key_clicked)
        self.kbw.keyDoubleClicked.connect(self._key_double)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.cellDoubleClicked.connect(lambda *_: self._edit())
        self.btn_edit.clicked.connect(self._edit)
        self.btn_clear.clicked.connect(self._clear)
        self.btn_restore.clicked.connect(self._restore)
        state.contextChanged.connect(self.refresh)
        state.dataChanged.connect(self.refresh)
        state.layoutChanged.connect(self._layout_changed)
        state.navigateKey.connect(self.show_combo)
        self.live.toggled.connect(self._live_toggled)
        QApplication.instance().installEventFilter(self)
        self._reset_banner()
        self.refresh()

    # ------------------------------------------------------------------
    def set_layer(self, lid: str) -> None:
        self.layer = lid
        self._show_layer(lid)
        self._select_layer_row(lid)

    def _show_layer(self, lid: str) -> None:
        self.shown_layer = lid
        self.layer_buttons[lid].setChecked(True)
        self.kbw.set_data(self.state.layout, self.state.keyboard, lid)

    # ------------------------------------------------------------------
    # Illumination des touches pressées
    # ------------------------------------------------------------------
    def _live_toggled(self, on: bool) -> None:
        self.state.settings.live_keys = on
        self.state.settings.save()
        if not on:
            self._release_all()
        self._reset_banner()

    def _reset_banner(self) -> None:
        if self.live.isChecked():
            self.banner.setText(f"<span style='color:{theme.MUTED}'>⌨  Appuyez sur une touche de votre clavier : "
                                "elle s'illumine ici et son action s'affiche. Maintenez Maj, Ctrl, Alt ou AltGr "
                                "pour voir la couche correspondante.</span>")
        else:
            self.banner.setText(f"<span style='color:{theme.MUTED}'>Illumination des touches désactivée.</span>")

    def _capturing(self) -> bool:
        if not (self.live.isChecked() and self.isVisible() and self.window().isActiveWindow()):
            return False
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return False
        fw = QApplication.focusWidget()
        # ne pas voler la saisie d'un champ de texte (ex. filtre du sélecteur de contexte)
        return not isinstance(fw, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox))

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:  # noqa: N802
        t = ev.type()
        if t in (QEvent.KeyPress, QEvent.KeyRelease):
            if not obj.isWidgetType() or not self._capturing():
                return False
            if not ev.isAutoRepeat():
                self.handle_key(ev, t == QEvent.KeyPress)
            # Alt+F4 doit toujours pouvoir fermer la fenêtre
            if ev.key() == Qt.Key_F4 and ev.modifiers() & Qt.AltModifier:
                return False
            return True
        if t in (QEvent.ApplicationDeactivate, QEvent.WindowDeactivate) and self.held:
            self._release_all()
        return False

    def hideEvent(self, ev) -> None:  # noqa: N802
        self._release_all()
        super().hideEvent(ev)

    def _release_all(self) -> None:
        self.held.clear()
        self.kbw.set_pressed(set())
        if self.shown_layer != self.layer:
            self._show_layer(self.layer)

    def key_id_for_event(self, ev: QKeyEvent) -> Optional[str]:
        kid = self.scanmap.get(ev.nativeScanCode())
        if kid is not None:
            return kid
        # repli (autre système, code inconnu) : via le caractère produit
        r = event_to_fg(ev)
        if r is None:
            return None
        lay = self.state.layout
        found = lay.find_inputs(*r) or lay.find_code(r[0])
        return found[0][0].id if found else None

    def handle_key(self, ev: QKeyEvent, down: bool) -> None:
        kid = self.key_id_for_event(ev)
        if kid is None:
            return
        if down:
            self.held.add(kid)
        else:
            self.held.discard(kid)
        self.kbw.set_pressed(self.held)
        target = live_layer(self.held & MODIFIER_KEY_IDS, self.state.layout.has_altgr) or self.layer
        if target != self.shown_layer:
            self._show_layer(target)
        if down and kid not in MODIFIER_KEY_IDS:
            k = self.state.layout.key(kid)
            self.current_key = k
            self.kbw.set_highlight(set())
            self.kbw.set_selected(kid)
            self._fill_detail()
            self._select_layer_row(target)
            self._announce(k, target)

    def _announce(self, k: PhysKey, layer: str) -> None:
        vis = self.kbw.visual(k.id)
        name = k.display_name
        if layer != "none":
            name = f"{LAYER_NAME[layer]}+{name}"
        if vis is None or vis.origin == "modifier":
            self.banner.setText(f"<b>{name}</b>")
            return
        code = f"<span style='color:{theme.MUTED}'>code FlightGear {vis.code}</span>" if vis.code is not None else ""
        if vis.action:
            col = theme.ORIGIN_COLORS.get(vis.origin)
            col = col.lighter(160).name() if col is not None else theme.TEXT
            pre = "↺ par repli : " if vis.fallback else ""
            txt = (f"⌨  <b>{name}</b>  →  <span style='color:{col}'><b>{pre}{vis.action}</b></span>"
                   f"  ·  {vis.combo}  ·  {code}")
        else:
            txt = (f"⌨  <b>{name}</b>  →  <span style='color:{theme.GREEN}'>aucune action (combinaison libre)</span>"
                   f"  ·  {code}")
        self.banner.setText(txt)

    def refresh(self) -> None:
        self.ctx_label.setText(f"Contexte : {self.state.ws.context_label(self.state.context)}")
        self.layer_buttons["altgr"].setEnabled(self.state.layout.has_altgr)
        if self.layer == "altgr" and not self.state.layout.has_altgr:
            self.layer = "none"
            self.layer_buttons["none"].setChecked(True)
        if self.shown_layer == "altgr" and not self.state.layout.has_altgr:
            self.shown_layer = self.layer
        sel = self._selected()
        self.kbw.set_data(self.state.layout, self.state.keyboard, self.shown_layer)
        self._fill_detail()
        self._select_layer_row(sel[2] if sel else self.layer)

    def _layout_changed(self) -> None:
        self.scanmap = scancode_map(self.state.layout)
        self._release_all()
        self.current_key = None
        self.kbw.set_selected(None)
        self.kbw.set_highlight(set())
        self.refresh()

    def show_combo(self, code: int, mask: int) -> None:
        """Met en évidence la touche correspondant à une combinaison."""
        found = self.state.layout.find_inputs(code, mask) or self.state.layout.find_code(code)
        if not found:
            self.kbw.set_highlight(set())
            self.key_title.setText(combo_label(code, mask))
            self.key_info.setText("Cette combinaison n'existe pas sur la disposition de clavier choisie.")
            return
        k, lid = found[0]
        self.set_layer(lid)
        self.kbw.set_highlight({k.id for k, _ in found})
        self.kbw.set_selected(k.id)
        self.current_key = k
        self._fill_detail()
        self._select_layer_row(lid)

    def _key_clicked(self, kid: str) -> None:
        self.current_key = self.state.layout.key(kid)
        self.kbw.set_highlight(set())
        self._fill_detail()
        self._select_layer_row(self.shown_layer)

    def _key_double(self, kid: str) -> None:
        self._key_clicked(kid)
        self._edit()

    # ------------------------------------------------------------------
    def _fill_detail(self) -> None:
        k = self.current_key
        self.table.setRowCount(0)
        if k is None:
            self.key_title.setText("Cliquez sur une touche")
            self.key_info.setText("Double-cliquez pour assigner directement une action. "
                                  "Survolez une touche pour voir le détail.")
            self._update_buttons()
            return
        self.key_title.setText(k.label or (k.base or "?").upper())
        info = []
        if not k.bindable:
            info.append("Touche de modification : elle ne peut pas être assignée seule.")
        if k.note:
            info.append(k.note)
        self.key_info.setText("   ".join(info))
        if not k.bindable:
            self._update_buttons()
            return
        kb = self.state.keyboard
        lay = self.state.layout
        for lid, name, _ in LAYERS:
            if lid == "altgr" and not lay.has_altgr:
                continue
            ki = k.input_for(lid)
            if ki is None:
                continue
            res = kb.resolve(ki.code, ki.mask)
            direct = kb.slot(ki.code, ki.mask)
            row = self.table.rowCount()
            self.table.insertRow(row)
            it = QTableWidgetItem(name)
            edit_mask = ki.mask
            self.table.setItem(row, 0, it)
            self.table.setItem(row, 1, QTableWidgetItem(combo_label(ki.code, ki.mask)))
            if direct is not None and (direct.is_bound or direct.is_disabled):
                action = direct.description() if direct.is_bound else "Désactivé pour cet aéronef"
                origin = direct.origin
            elif res.slot is not None and res.slot.is_bound and (not res.fallback or lid == "altgr"):
                # majuscule / ponctuation : Maj fait partie du caractère produit
                action = res.slot.description()
                origin = res.slot.origin
                edit_mask = res.used_mask
            elif res.slot is not None and res.slot.is_bound:
                action = "↺ " + res.slot.description()
                origin = "fallback"
            else:
                action, origin = "", "none"
            it.setData(Qt.UserRole, (ki.code, edit_mask, lid))
            a_item = QTableWidgetItem(action or "—")
            if origin in ("fallback", "none"):
                a_item.setForeground(QColor(theme.MUTED))
            if origin == "fallback":
                a_item.setToolTip(f"Aucune action propre : FlightGear exécute celle de "
                                  f"{combo_label(ki.code, res.used_mask)}.")
            self.table.setItem(row, 2, a_item)
            o_txt = {"fallback": "Repli", "none": "Libre"}.get(origin, theme.ORIGIN_LABELS.get(origin, origin))
            o_item = QTableWidgetItem(o_txt)
            col = theme.ORIGIN_COLORS.get(origin)
            if col is not None and origin not in ("none",):
                o_item.setForeground(col.lighter(150))
            self.table.setItem(row, 3, o_item)
            self.table.setItem(row, 4, QTableWidgetItem(str(ki.code)))
        self._update_buttons()

    def _select_layer_row(self, lid: str) -> None:
        for r in range(self.table.rowCount()):
            d = self.table.item(r, 0).data(Qt.UserRole)
            if d and d[2] == lid:
                self.table.selectRow(r)
                return

    def _selected(self) -> Optional[tuple[int, int, str]]:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole)

    def _update_buttons(self) -> None:
        sel = self._selected()
        ok = sel is not None and self.state.ws.ok
        self.btn_edit.setEnabled(ok)
        if not ok:
            self.btn_clear.setEnabled(False)
            self.btn_restore.setVisible(False)
            return
        code, mask, _ = sel
        slot = self.state.keyboard.slot(code, mask)
        self.btn_clear.setEnabled(bool(slot and slot.is_bound))
        self.btn_clear.setText("Effacer" if self.state.context.is_global else "Désactiver pour l'aéronef")
        self.btn_restore.setVisible(not self.state.context.is_global and bool(slot) and
                                    slot.origin in ("aircraft", "disabled"))

    def _edit(self) -> None:
        sel = self._selected()
        if sel is None:
            return
        code, mask, _ = sel
        ops.edit_key(self, self.state, code, mask)

    def _clear(self) -> None:
        sel = self._selected()
        if sel is not None:
            ops.clear_key(self, self.state, sel[0], sel[1])

    def _restore(self) -> None:
        sel = self._selected()
        if sel is not None:
            ops.restore_key(self, self.state, sel[0], sel[1])
