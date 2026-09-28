"""FGKeybinds launcher (double-click on Windows, or PyInstaller entry point)."""

import sys

from fgkeybinds.app import main

if __name__ == "__main__":
    sys.exit(main())
