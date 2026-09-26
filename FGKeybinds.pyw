"""Lanceur de FGKeybinds (double-clic sous Windows, ou point d'entrée PyInstaller)."""

import sys

from fgkeybinds.app import main

if __name__ == "__main__":
    sys.exit(main())
