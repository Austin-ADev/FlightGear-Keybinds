"""Page « Aéronefs » : bibliothèque et configurations propres à chaque avion."""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.aircraft import AircraftVariant
from ..core.keyboard import combo_label
from ..core.search import fold
from ..core.workspace import Context
from . import theme
from .profile_dialogs import ExportDialog, copy_to_aircraft_flow, import_profile_flow
from .state import AppState

STATUS_LABELS = {
    "ajout": ("Ajout", theme.GREEN),
    "remplace": ("Remplace le global", theme.AMBER),
    "identique": ("Identique au global", theme.MUTED),
    "désactivé": ("Désactive le global", theme.RED),
}


class AircraftPage(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.variant: Optional[AircraftVariant] = None
        self._meta_queue: list[AircraftVariant] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrer les aéronefs…")
        self.filter.setClearButtonEnabled(True)
        ll.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Aéronef", "Variante"])
        self.tree.setColumnWidth(0, 200)
        ll.addWidget(self.tree, 1)
        self.lib_info = QLabel()
        self.lib_info.setProperty("muted", True)
        self.lib_info.setWordWrap(True)
        ll.addWidget(self.lib_info)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        card = QFrame()
        card.setProperty("card", True)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        self.title = QLabel("Sélectionnez un aéronef")
        self.title.setProperty("heading", True)
        self.title.setWordWrap(True)
        cl.addWidget(self.title)
        self.meta = QLabel()
        self.meta.setProperty("muted", True)
        self.meta.setWordWrap(True)
        self.meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.meta.setTextFormat(Qt.RichText)
        cl.addWidget(self.meta)
        bar = QHBoxLayout()
        self.btn_use = QPushButton("Afficher sur le clavier")
        self.btn_use.setProperty("primary", True)
        self.btn_use.setToolTip("Utiliser cet aéronef comme contexte de travail")
        self.btn_export = QPushButton("Exporter un profil…")
        self.btn_import = QPushButton("Importer un profil…")
        self.btn_copy = QPushButton("Copier vers un autre aéronef…")
        self.btn_folder = QPushButton("Ouvrir le dossier")
        for b in (self.btn_use, self.btn_export, self.btn_import, self.btn_copy, self.btn_folder):
            bar.addWidget(b)
        bar.addStretch(1)
        cl.addLayout(bar)
        rl.addWidget(card)
        sub = QLabel("Raccourcis propres à cet aéronef")
        sub.setStyleSheet("font-size: 12pt; font-weight: 700; margin-top: 8px;")
        rl.addWidget(sub)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Combinaison", "Action de l'aéronef", "Action globale", "Statut",
                                              "Fichier"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        rl.addWidget(self.table, 1)
        self.errors = QLabel()
        self.errors.setWordWrap(True)
        self.errors.setStyleSheet(f"color: {theme.AMBER}")
        rl.addWidget(self.errors)
        split.addWidget(right)
        split.setSizes([380, 950])

        self.meta_timer = QTimer(self)
        self.meta_timer.timeout.connect(self._load_meta_chunk)
        self.filter.textChanged.connect(self._fill_tree)
        self.tree.currentItemChanged.connect(self._pick)
        self.table.cellDoubleClicked.connect(self._open_key)
        self.btn_use.clicked.connect(self._use)
        self.btn_export.clicked.connect(lambda: ExportDialog(self, state, self._ctx()).exec() if self.variant else None)
        self.btn_import.clicked.connect(lambda: import_profile_flow(self, state, self._ctx()) if self.variant else None)
        self.btn_copy.clicked.connect(lambda: copy_to_aircraft_flow(self, state, self._ctx()) if self.variant else None)
        self.btn_folder.clicked.connect(lambda: os.startfile(str(self.variant.aircraft_dir)) if self.variant else None)
        state.dataChanged.connect(self._data_changed)
        self._fill_tree()
        self._update_buttons()
        self._start_meta()

    def _ctx(self) -> Context:
        return Context("aircraft", self.variant.set_file)

    # -- arbre -------------------------------------------------------------
    def _fill_tree(self) -> None:
        q = fold(self.filter.text().strip())
        ws = self.state.ws
        cur = self.variant.key if self.variant else None
        self.tree.blockSignals(True)
        self.tree.clear()
        n = 0
        select = None
        for e in ws.library:
            vs = []
            for v in e.variants:
                label = ws.variant_label(v)
                if q and q not in fold(e.name + " " + label):
                    continue
                vs.append((v, label))
            if not vs:
                continue
            top = QTreeWidgetItem([e.name, f"{len(e.variants)} variante(s)"])
            top.setToolTip(0, str(e.dir))
            top.setData(0, Qt.UserRole, vs[0][0].key)
            self.tree.addTopLevelItem(top)
            for v, label in vs:
                it = QTreeWidgetItem([v.id, label.split(" — ", 1)[1] if " — " in label else ""])
                it.setData(0, Qt.UserRole, v.key)
                it.setToolTip(0, str(v.set_file))
                top.addChild(it)
                n += 1
                if v.key == cur:
                    select = it
            if q:
                top.setExpanded(True)
        self.tree.blockSignals(False)
        if select is not None:
            self.tree.setCurrentItem(select)
        roots = "<br>".join(str(d) for d in ws.paths.aircraft_dirs) or "aucun"
        self.lib_info.setText(f"{n} variante(s). Dossiers analysés :<br>{roots}<br>"
                              "Ajoutez vos propres dossiers dans les paramètres.")
        self.lib_info.setTextFormat(Qt.RichText)

    def _start_meta(self) -> None:
        ws = self.state.ws
        self._meta_queue = [v for v in ws.variants() if ws.cached_meta(v) is None]
        if self._meta_queue:
            self.meta_timer.start(0)

    def _load_meta_chunk(self) -> None:
        ws = self.state.ws
        for _ in range(8):
            if not self._meta_queue:
                self.meta_timer.stop()
                self._fill_tree()
                self.state.labelsChanged.emit()
                return
            ws.meta(self._meta_queue.pop(0))

    def _data_changed(self) -> None:
        if not self._meta_queue:
            self._start_meta()
        if self.variant is not None and self.state.ws.variant(self.variant.set_file) is None:
            self.variant = None
        self._fill_tree()
        self._show()

    def _pick(self, item: Optional[QTreeWidgetItem], _prev=None) -> None:
        if item is None:
            return
        key = item.data(0, Qt.UserRole)
        self.variant = self.state.ws.variant(key) if key else None
        self._show()

    # -- détail ---------------------------------------------------------------
    def _update_buttons(self) -> None:
        on = self.variant is not None
        for b in (self.btn_use, self.btn_export, self.btn_import, self.btn_copy, self.btn_folder):
            b.setEnabled(on)

    def _show(self) -> None:
        self._update_buttons()
        self.table.setRowCount(0)
        self.errors.setText("")
        v = self.variant
        if v is None:
            self.title.setText("Sélectionnez un aéronef")
            self.meta.setText("Choisissez un aéronef dans la liste pour voir ses raccourcis spécifiques, "
                              "les exporter ou les copier vers un autre aéronef.")
            return
        ws = self.state.ws
        m = ws.meta(v)
        self.title.setText(m.description or v.id)
        ai = ws.aircraft_input(v)
        lines = [f"Variante <b>{v.id}</b> · {v.set_file}"]
        if m.author:
            lines.append(f"Auteur(s) : {m.author}")
        if m.flight_model:
            lines.append(f"Modèle de vol : {m.flight_model}" + (f" · statut : {m.status}" if m.status else ""))
        if ai.sources:
            files = []
            for s in ai.sources:
                if not s.exists and not s.dedicated:
                    continue
                tag = "" if s.editable else " <span style='color:%s'>(partagé, lecture seule)</span>" % theme.AMBER
                files.append(f"{s.path.name}{tag}")
            if files:
                lines.append("Fichiers clavier : " + ", ".join(files))
        prim = ai.primary_keyboard_file
        if prim is not None:
            lines.append(f"Les nouvelles touches seront écrites dans : {prim.path}")
        entry = ws.entry_of(v)
        if entry is not None and len(entry.variants) > 1 and prim is not None and prim.path != v.set_file:
            lines.append("Remarque : ce fichier peut être partagé par plusieurs variantes de l'aéronef.")
        self.meta.setText("<br>".join(lines))
        rows = ws.aircraft_specific_slots(v)
        self.table.setSortingEnabled(False)
        for s, g, status in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            it = QTableWidgetItem(combo_label(s.code, s.mask))
            it.setData(Qt.UserRole, (s.code, s.mask))
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem(s.description() if s.is_bound else "(désactivé)"))
            gi = QTableWidgetItem(g.description() if g is not None and g.is_bound else "—")
            gi.setForeground(QColor(theme.MUTED))
            self.table.setItem(r, 2, gi)
            lbl, col = STATUS_LABELS.get(status, (status, theme.MUTED))
            si = QTableWidgetItem(lbl)
            si.setForeground(QColor(col))
            self.table.setItem(r, 3, si)
            files = sorted({src.path.name for b in s.press + s.release for src in b.node.sources
                            if src.phase == "aircraft"})
            self.table.setItem(r, 4, QTableWidgetItem(", ".join(files)))
        self.table.setSortingEnabled(True)
        if not rows:
            self.table.setRowCount(1)
            e = QTableWidgetItem("Cet aéronef utilise uniquement les raccourcis globaux de FlightGear.")
            e.setForeground(QColor(theme.MUTED))
            self.table.setItem(0, 1, e)
        if ai.errors:
            self.errors.setText("Avertissements de chargement : " + " ; ".join(ai.errors[:4]))

    def _use(self) -> None:
        if self.variant is not None:
            self.state.set_context(self._ctx())
            self.window().show_tab("keyboard")

    def _open_key(self, row: int, _col: int) -> None:
        it = self.table.item(row, 0)
        if it is None or self.variant is None:
            return
        d = it.data(Qt.UserRole)
        if not d:
            return
        self.state.set_context(self._ctx())
        self.window().show_tab("keyboard")
        self.state.navigateKey.emit(d[0], d[1])
