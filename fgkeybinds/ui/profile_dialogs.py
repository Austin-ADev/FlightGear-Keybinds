"""Dialogues d'export, d'import et de copie de profils."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import xmledit
from ..core.bindings import bindings_equal, describe_bindings
from ..core.profiles import JoystickEntry, Profile, SlotEntry, keyboard_xml, load_profile, save_profile
from ..core.workspace import GLOBAL, Context
from . import ops, theme
from .state import AppState


def context_combo(state: AppState, include_global: bool = True, exclude: Optional[Context] = None) -> QComboBox:
    cb = QComboBox()
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.NoInsert)
    if include_global:
        cb.addItem("FlightGear (global)", "")
    for v in state.ws.variants():
        if exclude is not None and not exclude.is_global and v.set_file == exclude.set_file:
            continue
        cb.addItem(state.ws.variant_label(v), str(v.set_file))
    comp = cb.completer()
    comp.setFilterMode(Qt.MatchContains)
    comp.setCompletionMode(QCompleter.PopupCompletion)
    return cb


def ctx_from_data(d: str) -> Context:
    return GLOBAL if not d else Context("aircraft", Path(d))


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class ExportDialog(QDialog):
    def __init__(self, parent, state: AppState, ctx: Context):
        super().__init__(parent)
        self.state = state
        self.ctx = ctx
        self.setWindowTitle("Exporter un profil")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        h = QLabel("Exporter un profil")
        h.setProperty("heading", True)
        lay.addWidget(h)
        src = QLabel(f"Source : {state.ws.context_label(ctx)}")
        src.setProperty("muted", True)
        lay.addWidget(src)
        form = QFormLayout()
        self.name = QLineEdit(state.ws.context_label(ctx))
        form.addRow("Nom du profil", self.name)
        scope = QWidget()
        sl = QVBoxLayout(scope)
        sl.setContentsMargins(0, 0, 0, 0)
        self.only_specific = QRadioButton("Uniquement les raccourcis propres à cet aéronef")
        self.all_effective = QRadioButton("Tous les raccourcis effectifs (global + aéronef)")
        if ctx.is_global:
            self.only_specific.setEnabled(False)
            self.all_effective.setChecked(True)
            self.all_effective.setText("Tous les raccourcis globaux")
        else:
            self.only_specific.setChecked(True)
        sl.addWidget(self.only_specific)
        sl.addWidget(self.all_effective)
        form.addRow("Contenu clavier", scope)
        self.with_js = QCheckBox("Inclure les configurations des périphériques branchés")
        self.with_js.setChecked(bool(state.ws.joystick_configs_for_bindings()))
        self.with_js.setEnabled(bool(state.ws.joystick_configs_for_bindings()))
        form.addRow("Périphériques", self.with_js)
        fmt = QWidget()
        fl = QVBoxLayout(fmt)
        fl.setContentsMargins(0, 0, 0, 0)
        self.fmt_json = QRadioButton("Profil FGKeybinds (.fgkb) — clavier et périphériques, réimportable")
        self.fmt_xml = QRadioButton("Fichier clavier FlightGear (.xml) — utilisable directement dans un aéronef")
        self.fmt_json.setChecked(True)
        fl.addWidget(self.fmt_json)
        fl.addWidget(self.fmt_xml)
        form.addRow("Format", fmt)
        lay.addLayout(form)
        self.summary = QLabel()
        self.summary.setProperty("muted", True)
        lay.addWidget(self.summary)
        bb = QDialogButtonBox()
        ok = bb.addButton("Exporter…", QDialogButtonBox.AcceptRole)
        ok.setProperty("primary", True)
        bb.addButton("Annuler", QDialogButtonBox.RejectRole)
        lay.addWidget(bb)
        bb.accepted.connect(self._export)
        bb.rejected.connect(self.reject)
        for w in (self.only_specific, self.all_effective, self.with_js, self.fmt_json, self.fmt_xml):
            w.toggled.connect(self._update)
        self._update()

    def _entries(self) -> list[SlotEntry]:
        return self.state.ws.entries_for(self.ctx, only_specific=self.only_specific.isChecked())

    def _update(self) -> None:
        n = len(self._entries())
        js = len(self.state.ws.joystick_configs_for_bindings()) if self.with_js.isChecked() else 0
        self.with_js.setEnabled(self.fmt_json.isChecked() and bool(self.state.ws.joystick_configs_for_bindings()))
        txt = f"{n} combinaison(s) de touches"
        if js and self.fmt_json.isChecked():
            txt += f", {js} configuration(s) de périphérique"
        self.summary.setText(txt + ".")

    def _export(self) -> None:
        entries = self._entries()
        base = "".join(c if c.isalnum() or c in "-_ " else "_" for c in self.name.text()).strip() or "profil"
        if self.fmt_json.isChecked():
            path, _ = QFileDialog.getSaveFileName(self, "Exporter le profil", base + ".fgkb",
                                                  "Profil FGKeybinds (*.fgkb)")
            if not path:
                return
            joys = []
            if self.with_js.isChecked():
                for cfg in self.state.ws.joystick_configs_for_bindings():
                    try:
                        joys.append(JoystickEntry(cfg.names, cfg.path.read_text(encoding="utf-8", errors="replace")))
                    except OSError:
                        pass
            src = {"context": self.ctx.kind}
            if not self.ctx.is_global:
                v = self.state.ws.variant(self.ctx.set_file)
                src.update({"aircraft": v.id if v else "", "set_file": str(self.ctx.set_file)})
            save_profile(Profile(self.name.text(), entries, joys, src), Path(path))
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Exporter le fichier clavier", base + "-keyboard.xml",
                                                  "Fichier XML FlightGear (*.xml)")
            if not path:
                return
            Path(path).write_text(keyboard_xml(entries, f"Exporté par FGKeybinds : {self.name.text()}"),
                                  encoding="utf-8")
        self.state.status.emit(f"Profil exporté : {path}")
        self.accept()


# ---------------------------------------------------------------------------
# Import / copie
# ---------------------------------------------------------------------------

class ImportDialog(QDialog):
    """Sélection des entrées d'un profil puis application à un contexte cible."""

    def __init__(self, parent, state: AppState, profile: Profile, target: Optional[Context] = None,
                 title: str = "Importer un profil", exclude: Optional[Context] = None):
        super().__init__(parent)
        self.state = state
        self.profile = profile
        self.setWindowTitle(title)
        self.resize(1000, 620)
        lay = QVBoxLayout(self)
        h = QLabel(title)
        h.setProperty("heading", True)
        lay.addWidget(h)
        src = QLabel(f"Profil : <b>{profile.name}</b> — {len(profile.keyboard)} combinaison(s), "
                     f"{len(profile.joysticks)} périphérique(s)")
        src.setTextFormat(Qt.RichText)
        lay.addWidget(src)
        tl = QHBoxLayout()
        tl.addWidget(QLabel("Appliquer à :"))
        self.target = context_combo(state, True, exclude)
        if target is not None:
            i = self.target.findData(target.key)
            if i >= 0:
                self.target.setCurrentIndex(i)
        elif exclude is not None and self.target.count() > 1:
            self.target.setCurrentIndex(1)  # copie : un aéronef par défaut plutôt que le global
        tl.addWidget(self.target, 1)
        lay.addLayout(tl)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Combinaison", "Action importée", "Action actuelle dans la cible", "État"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        lay.addWidget(self.table, 1)
        sel = QHBoxLayout()
        b_all = QPushButton("Tout cocher")
        b_none = QPushButton("Tout décocher")
        b_new = QPushButton("Seulement les différences")
        for b in (b_all, b_none, b_new):
            sel.addWidget(b)
        sel.addStretch(1)
        lay.addLayout(sel)
        self.js_checks: list[tuple[QCheckBox, JoystickEntry]] = []
        if profile.joysticks:
            jl = QLabel("Configurations de périphériques à installer dans FG_HOME :")
            jl.setStyleSheet("font-weight:600; margin-top:6px")
            lay.addWidget(jl)
            for j in profile.joysticks:
                cb = QCheckBox(", ".join(n for n in j.names if n) or "(sans nom)")
                cb.setChecked(True)
                lay.addWidget(cb)
                self.js_checks.append((cb, j))
        bb = QDialogButtonBox()
        ok = bb.addButton("Appliquer", QDialogButtonBox.AcceptRole)
        ok.setProperty("primary", True)
        bb.addButton("Annuler", QDialogButtonBox.RejectRole)
        lay.addWidget(bb)
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        b_all.clicked.connect(lambda: self._check(lambda r: True))
        b_none.clicked.connect(lambda: self._check(lambda r: False))
        b_new.clicked.connect(lambda: self._check(lambda r: self._states[r] != "identique"))
        self.target.currentIndexChanged.connect(self._fill)
        self._states: list[str] = []
        self._fill()

    def _ctx(self) -> Context:
        return ctx_from_data(self.target.currentData() or "")

    def _fill(self) -> None:
        kb = self.state.ws.keyboard(self._ctx())
        self.table.setRowCount(0)
        self._states = []
        for e in self.profile.keyboard:
            r = self.table.rowCount()
            self.table.insertRow(r)
            it = QTableWidgetItem(e.label or f"{e.code}/{e.mask}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            self.table.setItem(r, 0, it)
            new_txt = describe_bindings(e.press_nodes(), e.desc) or (
                "Au relâchement : " + describe_bindings(e.release_nodes()) if e.release else "(désactivation)")
            self.table.setItem(r, 1, QTableWidgetItem(new_txt))
            cur = kb.slot(e.code, e.mask)
            if cur is not None and cur.is_bound:
                cur_txt = cur.description()
                same = bindings_equal([b.node for b in cur.press], e.press_nodes()) and bindings_equal(
                    [b.node for b in cur.release], e.release_nodes())
                state = "identique" if same else "remplace"
            else:
                cur_txt = "—"
                state = "ajout"
            self._states.append(state)
            ci = QTableWidgetItem(cur_txt)
            ci.setForeground(QColor(theme.MUTED))
            self.table.setItem(r, 2, ci)
            si = QTableWidgetItem({"identique": "Identique", "remplace": "Remplace", "ajout": "Nouveau"}[state])
            si.setForeground(QColor({"identique": theme.MUTED, "remplace": theme.AMBER, "ajout": theme.GREEN}[state]))
            self.table.setItem(r, 3, si)
            it.setCheckState(Qt.Unchecked if state == "identique" else Qt.Checked)

    def _check(self, pred) -> None:
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(Qt.Checked if pred(r) else Qt.Unchecked)

    def _apply(self) -> None:
        ctx = self._ctx()
        chosen = [e for r, e in enumerate(self.profile.keyboard)
                  if self.table.item(r, 0).checkState() == Qt.Checked]
        joys = [j for cb, j in self.js_checks if cb.isChecked()]
        if not chosen and not joys:
            QMessageBox.information(self, "Rien à appliquer", "Aucune entrée n'est cochée.")
            return
        if chosen and ctx.is_global and not ops.confirm_global_write(self, self.state):
            return
        try:
            written = self.state.ws.apply_entries(ctx, chosen) if chosen else []
            for j in joys:
                written.append(self._install_joystick(j))
        except (xmledit.EditError, OSError, ValueError) as e:
            ops.error(self, e)
            self.state.dataChanged.emit()
            return
        if joys:
            self.state.ws.reload_joysticks()
            self.state.devicesChanged.emit()
        self.state.after_write(written[-1] if written else None)
        QMessageBox.information(self, "Terminé",
                                f"{len(chosen)} combinaison(s) appliquée(s) à « {self.state.ws.context_label(ctx)} »"
                                + (f" et {len(joys)} configuration(s) de périphérique installée(s)." if joys else "."))
        self.accept()

    def _install_joystick(self, j: JoystickEntry) -> Path:
        d = self.state.ws.user_joystick_dir()
        d.mkdir(parents=True, exist_ok=True)
        name = next((n for n in j.names if n and n.lower() != "default"), "joystick")
        dest = d / (xmledit.sanitize_filename(name) + ".xml")
        if dest.exists():
            xmledit.ensure_backup(dest)
        dest.write_text(j.xml, encoding="utf-8")
        return dest


def import_profile_flow(parent: QWidget, state: AppState, target: Optional[Context] = None) -> None:
    path, _ = QFileDialog.getOpenFileName(parent, "Importer un profil", "",
                                          "Profils et fichiers FlightGear (*.fgkb *.xml);;Tous les fichiers (*)")
    if not path:
        return
    try:
        prof = load_profile(Path(path))
    except (ValueError, OSError) as e:
        QMessageBox.critical(parent, "Profil illisible", str(e))
        return
    ImportDialog(parent, state, prof, target or state.context).exec()


def copy_to_aircraft_flow(parent: QWidget, state: AppState, source: Context) -> None:
    ws = state.ws
    entries = ws.entries_for(source, only_specific=not source.is_global)
    if not entries:
        QMessageBox.information(parent, "Rien à copier", "Ce contexte n'a aucun raccourci spécifique à copier.")
        return
    prof = Profile(name=ws.context_label(source), keyboard=entries)
    ImportDialog(parent, state, prof, None, "Copier les raccourcis vers un autre aéronef", exclude=source).exec()
