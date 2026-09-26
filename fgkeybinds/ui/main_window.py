"""Fenêtre principale."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QWidget,
)

from .. import APP_NAME, VERSION_LABEL, __version__
from ..core.workspace import GLOBAL, Context
from . import theme
from .dialogs import AboutDialog, BackupsDialog, SettingsDialog
from .icon import app_icon
from .page_aircraft import AircraftPage
from .page_devices import DevicesPage
from .page_keyboard import KeyboardPage
from .page_search import SearchPage
from .page_unbound import UnboundPage
from .profile_dialogs import ExportDialog, import_profile_flow
from .state import AppState


class MainWindow(QMainWindow):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.setWindowTitle(f"{APP_NAME} {VERSION_LABEL} — raccourcis FlightGear")
        self.setWindowIcon(app_icon())
        self.resize(1480, 920)

        tb = QToolBar()
        tb.setMovable(False)
        tb.setFloatable(False)
        self.addToolBar(tb)
        brand = QLabel(f"  ✈  <b>{APP_NAME}</b>  ")
        brand.setTextFormat(Qt.RichText)
        brand.setStyleSheet(f"font-size: 13pt; color: {theme.ACCENT};")
        tb.addWidget(brand)
        tb.addSeparator()
        tb.addWidget(QLabel(" Contexte : "))
        self.ctx_combo = QComboBox()
        self.ctx_combo.setEditable(True)
        self.ctx_combo.setInsertPolicy(QComboBox.NoInsert)
        self.ctx_combo.setMinimumWidth(380)
        self.ctx_combo.setToolTip("Configuration affichée : globale ou propre à un aéronef "
                                  "(tapez pour filtrer)")
        self.ctx_combo.completer().setFilterMode(Qt.MatchContains)
        self.ctx_combo.completer().setCompletionMode(QCompleter.PopupCompletion)
        tb.addWidget(self.ctx_combo)
        tb.addWidget(QLabel("   Clavier : "))
        self.layout_combo = QComboBox()
        for lay in state.ws.layouts:
            self.layout_combo.addItem(lay.name, lay.id)
        self.layout_combo.setCurrentIndex(max(0, self.layout_combo.findData(state.layout.id)))
        tb.addWidget(self.layout_combo)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        a_reload = tb.addAction("⟳ Recharger")
        a_reload.setToolTip("Relire les fichiers de FlightGear et détecter les périphériques")
        a_export = tb.addAction("Exporter…")
        a_import = tb.addAction("Importer…")
        a_backups = tb.addAction("Sauvegardes")
        a_settings = tb.addAction("Paramètres")
        a_about = tb.addAction("?")
        a_about.setToolTip("À propos")

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)
        self.setCentralWidget(self.tabs)
        self.pages = {
            "keyboard": KeyboardPage(state),
            "devices": DevicesPage(state),
            "search": SearchPage(state),
            "aircraft": AircraftPage(state),
            "unbound": UnboundPage(state),
        }
        self.tabs.addTab(self.pages["keyboard"], "⌨  Clavier")
        self.tabs.addTab(self.pages["devices"], "🎮  Périphériques")
        self.tabs.addTab(self.pages["search"], "🔍  Recherche")
        self.tabs.addTab(self.pages["aircraft"], "✈  Aéronefs")
        self.tabs.addTab(self.pages["unbound"], "○  Non assignées")

        self.status_label = QLabel()
        self.status_label.setProperty("muted", True)
        self.statusBar().addPermanentWidget(self.status_label)

        self._fill_contexts()
        self.ctx_combo.currentIndexChanged.connect(self._ctx_picked)
        self.layout_combo.currentIndexChanged.connect(
            lambda _i: state.set_layout(self.layout_combo.currentData()))
        state.contextChanged.connect(self._sync_ctx)
        state.labelsChanged.connect(self._fill_contexts)
        state.dataChanged.connect(self._update_status)
        state.status.connect(lambda m: self.statusBar().showMessage(m, 12000))
        self.pages["search"].goKeyboard.connect(lambda: self.show_tab("keyboard"))
        self.pages["search"].goDevices.connect(lambda: self.show_tab("devices"))
        a_reload.triggered.connect(self._reload)
        a_export.triggered.connect(lambda: ExportDialog(self, state, state.context).exec())
        a_import.triggered.connect(lambda: import_profile_flow(self, state))
        a_backups.triggered.connect(lambda: BackupsDialog(self, state).exec())
        a_settings.triggered.connect(lambda: SettingsDialog(self, state).exec())
        a_about.triggered.connect(lambda: AboutDialog(self, state).exec())
        self._update_status()
        geo = state.settings.window_geometry
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))

    # ------------------------------------------------------------------
    def show_tab(self, name: str) -> None:
        self.tabs.setCurrentWidget(self.pages[name])

    def _fill_contexts(self) -> None:
        ws = self.state.ws
        self.ctx_combo.blockSignals(True)
        self.ctx_combo.clear()
        self.ctx_combo.addItem("FlightGear (global)", "")
        for v in ws.variants():
            self.ctx_combo.addItem("✈ " + ws.variant_label(v), str(v.set_file))
        self.ctx_combo.blockSignals(False)
        self._sync_ctx()

    def _sync_ctx(self) -> None:
        i = self.ctx_combo.findData(self.state.context.key)
        self.ctx_combo.blockSignals(True)
        self.ctx_combo.setCurrentIndex(max(0, i))
        self.ctx_combo.blockSignals(False)
        self._update_status()

    def _ctx_picked(self, i: int) -> None:
        if i < 0:
            return
        d = self.ctx_combo.itemData(i)
        if d is None:
            return
        self.state.set_context(GLOBAL if not d else Context("aircraft", Path(d)))

    def _reload(self) -> None:
        self.state.reload()
        self._fill_contexts()
        self.statusBar().showMessage("Configuration rechargée.", 5000)

    def _update_status(self) -> None:
        p = self.state.ws.paths
        if p.fg_root is None:
            self.status_label.setText("FG_ROOT introuvable — ouvrez les Paramètres")
            return
        self.status_label.setText(f"FlightGear {p.version} · FG_ROOT {p.fg_root} · FG_HOME {p.fg_home}  ")

    # ------------------------------------------------------------------
    def startup_checks(self) -> None:
        ws = self.state.ws
        if ws.paths.fg_root is None:
            QMessageBox.warning(
                self, "FlightGear introuvable",
                "Le dossier de données de FlightGear (FG_ROOT, qui contient keyboard.xml) n'a pas été trouvé.\n"
                "Indiquez-le dans les paramètres.")
            SettingsDialog(self, self.state).exec()
            return
        miss = ws.journal_mismatches()
        if miss:
            r = QMessageBox.question(
                self, "Modifications globales absentes",
                f"{len(miss)} modification(s) que vous aviez apportée(s) aux raccourcis globaux ne sont plus "
                "présentes dans keyboard.xml (FlightGear a probablement été mis à jour).\n\n"
                "Voulez-vous les réappliquer maintenant ?")
            if r == QMessageBox.Yes:
                try:
                    ws.apply_entries(GLOBAL, miss)
                    self.state.after_write(ws.paths.fg_root / "keyboard.xml")
                except Exception as e:  # noqa: BLE001
                    QMessageBox.critical(self, "Erreur", str(e))

    def closeEvent(self, ev) -> None:  # noqa: N802
        self.state.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.state.settings.save()
        super().closeEvent(ev)


def version_string() -> str:
    return f"{APP_NAME} {__version__}"
