"""Dialogues « Paramètres », « Sauvegardes » et « À propos »."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, VERSION_LABEL
from ..core import xmledit
from ..core.settings import app_dir, user_actions_path, user_layouts_dir
from ..core.workspace import GLOBAL
from . import ops
from .state import AppState


def _path_row(edit: QLineEdit, parent: QWidget, title: str) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(edit, 1)
    b = QPushButton("Parcourir…")
    h.addWidget(b)

    def pick():
        d = QFileDialog.getExistingDirectory(parent, title, edit.text() or str(Path.home()))
        if d:
            edit.setText(d)

    b.clicked.connect(pick)
    return w


class SettingsDialog(QDialog):
    def __init__(self, parent, state: AppState):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Paramètres")
        self.setMinimumWidth(720)
        s = state.settings
        p = state.ws.paths
        lay = QVBoxLayout(self)
        h = QLabel("Paramètres")
        h.setProperty("heading", True)
        lay.addWidget(h)
        form = QFormLayout()
        self.root = QLineEdit(s.fg_root)
        self.root.setPlaceholderText(f"Détection automatique : {p.fg_root or 'introuvable'}")
        form.addRow("Données FlightGear (FG_ROOT)", _path_row(self.root, self, "Dossier FG_ROOT"))
        self.home = QLineEdit(s.fg_home)
        self.home.setPlaceholderText(f"Détection automatique : {p.fg_home}")
        form.addRow("Dossier utilisateur (FG_HOME)", _path_row(self.home, self, "Dossier FG_HOME"))
        lay.addLayout(form)
        lbl = QLabel("Dossiers d'aéronefs supplémentaires (en plus de ceux détectés automatiquement) :")
        lay.addWidget(lbl)
        self.dirs = QListWidget()
        self.dirs.addItems(s.extra_aircraft_dirs)
        lay.addWidget(self.dirs)
        hb = QHBoxLayout()
        b_add = QPushButton("Ajouter un dossier…")
        b_del = QPushButton("Retirer")
        hb.addWidget(b_add)
        hb.addWidget(b_del)
        hb.addStretch(1)
        lay.addLayout(hb)
        auto = QLabel("Détectés automatiquement :<br>" + "<br>".join(str(d) for d in p.aircraft_dirs))
        auto.setProperty("muted", True)
        auto.setTextFormat(Qt.RichText)
        auto.setWordWrap(True)
        lay.addWidget(auto)
        extra = QLabel(
            f"Personnalisation avancée :<br>• actions supplémentaires du catalogue : {user_actions_path()}<br>"
            f"• dispositions de clavier supplémentaires (JSON) : {user_layouts_dir()}")
        extra.setProperty("muted", True)
        extra.setTextFormat(Qt.RichText)
        extra.setWordWrap(True)
        extra.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(extra)
        bb = QDialogButtonBox()
        ok = bb.addButton("Enregistrer et recharger", QDialogButtonBox.AcceptRole)
        ok.setProperty("primary", True)
        bb.addButton("Cancel", QDialogButtonBox.RejectRole)
        lay.addWidget(bb)
        b_add.clicked.connect(self._add)
        b_del.clicked.connect(lambda: [self.dirs.takeItem(self.dirs.row(i)) for i in self.dirs.selectedItems()])
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)

    def _add(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Dossier contenant des aéronefs")
        if d:
            self.dirs.addItem(d)

    def _save(self) -> None:
        r = self.root.text().strip()
        if r and not (Path(r) / "keyboard.xml").is_file():
            QMessageBox.warning(self, "FG_ROOT invalide", "Ce dossier ne contient pas keyboard.xml.")
            return
        s = self.state.settings
        s.fg_root = r
        s.fg_home = self.home.text().strip()
        s.extra_aircraft_dirs = [self.dirs.item(i).text() for i in range(self.dirs.count())]
        s.save()
        self.state.reload()
        self.accept()


class BackupsDialog(QDialog):
    def __init__(self, parent, state: AppState):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Sauvegardes et fichiers modifiés")
        self.resize(900, 480)
        lay = QVBoxLayout(self)
        h = QLabel("Fichiers modifiés par FGKeybinds")
        h.setProperty("heading", True)
        lay.addWidget(h)
        info = QLabel("Avant sa première modification, chaque fichier est sauvegardé à côté de l'original "
                      f"(extension {xmledit.BACKUP_SUFFIX}). « Restaurer » remet le fichier d'origine ; pour une "
                      "copie de joystick créée par FGKeybinds, la copie est supprimée.")
        info.setWordWrap(True)
        info.setProperty("muted", True)
        lay.addWidget(info)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Fichier", "Sauvegarde"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        lay.addWidget(self.table, 1)
        self.journal = QLabel()
        self.journal.setWordWrap(True)
        lay.addWidget(self.journal)
        hb = QHBoxLayout()
        self.b_restore = QPushButton("Restaurer l'original")
        self.b_restore.setProperty("danger", True)
        self.b_folder = QPushButton("Ouvrir le dossier")
        self.b_reapply = QPushButton("Réappliquer mes modifications globales")
        hb.addWidget(self.b_restore)
        hb.addWidget(self.b_folder)
        hb.addStretch(1)
        hb.addWidget(self.b_reapply)
        close = QPushButton("Fermer")
        hb.addWidget(close)
        lay.addLayout(hb)
        self.b_restore.clicked.connect(self._restore)
        self.b_folder.clicked.connect(self._folder)
        self.b_reapply.clicked.connect(self._reapply)
        close.clicked.connect(self.accept)
        self._fill()

    def _fill(self) -> None:
        files = self.state.ws.modified_files()
        self.table.setRowCount(len(files))
        for r, f in enumerate(files):
            it = QTableWidgetItem(str(f))
            it.setData(Qt.UserRole, str(f))
            self.table.setItem(r, 0, it)
            b = xmledit.backup_path(f)
            self.table.setItem(r, 1, QTableWidgetItem("oui" if b.exists() else "copie créée par FGKeybinds"))
        n = len(self.state.ws.journal_entries())
        miss = self.state.ws.journal_mismatches()
        txt = f"Modifications globales mémorisées : {n}."
        if miss:
            txt += (f" <b>{len(miss)} ne sont plus présentes dans keyboard.xml</b> (mise à jour de FlightGear ?) : "
                    "cliquez sur « Réappliquer ».")
        self.journal.setText(txt)
        self.journal.setTextFormat(Qt.RichText)
        self.b_reapply.setEnabled(bool(miss))

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return [Path(self.table.item(r.row(), 0).data(Qt.UserRole)) for r in rows]

    def _restore(self) -> None:
        sel = self._selected()
        if not sel:
            return
        if QMessageBox.question(self, "Restaurer", "Restaurer l'état d'origine de :\n" +
                                "\n".join(str(p) for p in sel) + " ?") != QMessageBox.Yes:
            return
        for p in sel:
            self.state.ws.restore_file(p)
        self.state.ws.refresh_global()
        self.state.ws.reload_joysticks()
        self.state.dataChanged.emit()
        self.state.devicesChanged.emit()
        self._fill()

    def _folder(self) -> None:
        sel = self._selected()
        if sel:
            os.startfile(str(sel[0].parent))  # noqa: S606

    def _reapply(self) -> None:
        miss = self.state.ws.journal_mismatches()
        if not miss:
            return
        try:
            p = self.state.ws.apply_entries(GLOBAL, miss)
        except (xmledit.EditError, OSError) as e:
            ops.error(self, e)
            return
        self.state.after_write(p[-1] if p else None)
        self._fill()


class AboutDialog(QDialog):
    def __init__(self, parent, state: AppState):
        super().__init__(parent)
        self.setWindowTitle(f"À propos de {APP_NAME}")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        h = QLabel(f"{APP_NAME} {VERSION_LABEL}")
        h.setProperty("heading", True)
        lay.addWidget(h)
        p = state.ws.paths
        t = QLabel(
            "Gestionnaire des raccourcis clavier et des périphériques de FlightGear.<br><br>"
            f"FlightGear : {p.version or 'version inconnue'}<br>"
            f"FG_ROOT : {p.fg_root}<br>FG_HOME : {p.fg_home}<br>Données de l'application : {app_dir()}<br><br>"
            "<b>Où sont enregistrées les modifications ?</b><br>"
            "• Raccourcis globaux : FG_ROOT/keyboard.xml (sauvegarde automatique de l'original).<br>"
            "• Raccourcis d'un aéronef : fichier clavier de l'aéronef (ou son -set.xml).<br>"
            "• Périphériques : copie personnelle dans FG_HOME/Input/Joysticks/FGKeybinds, prioritaire sur "
            "les configurations fournies avec FlightGear.<br><br>"
            "Redémarrez FlightGear pour que les changements soient pris en compte.")
        t.setWordWrap(True)
        t.setTextFormat(Qt.RichText)
        t.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
