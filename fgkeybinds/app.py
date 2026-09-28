"""Entry point of the graphical application."""

from __future__ import annotations

import os
import sys
import traceback


def main() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import APP_NAME
    from .core.settings import Settings
    from .ui import theme
    from .ui.icon import app_icon

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setWindowIcon(app_icon())
    theme.apply(app)

    def excepthook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        sys.__stderr__ and sys.__stderr__.write(text)
        QMessageBox.critical(None, "Unexpected Error", f"{value}\n\n{text[-2500:]}")

    sys.excepthook = excepthook

    from .ui.main_window import MainWindow
    from .ui.state import AppState

    state = AppState(Settings.load())
    win = MainWindow(state)
    win.show()
    shot = os.environ.get("FGKB_SCREENSHOT")
    if shot:
        # diagnostic : capture de la fenêtre puis sortie (utilisé pour tester l'exécutable)
        def grab_and_quit():
            win.show_tab(os.environ.get("FGKB_TAB", "keyboard"))
            QTimer.singleShot(800, lambda: (win.grab().save(shot), app.quit()))

        QTimer.singleShot(2500, grab_and_quit)
    else:
        QTimer.singleShot(200, win.startup_checks)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
