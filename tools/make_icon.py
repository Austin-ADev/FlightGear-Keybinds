"""Generates build/fgkeybinds.ico (multiple sizes, PNG images) from the icon drawn by Qt."""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fgkeybinds.ui.icon import render  # noqa: E402


def png_bytes(size: int) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    render(size).save(buf, "PNG")
    return bytes(buf.data())


def main() -> None:
    app = QApplication([])  # noqa: F841
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [png_bytes(s) for s in sizes]
    out = Path(__file__).resolve().parent.parent / "build" / "fgkeybinds.ico"
    out.parent.mkdir(exist_ok=True)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, data in zip(sizes, images):
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out.write_bytes(header + entries + b"".join(images))
    print(out)


if __name__ == "__main__":
    main()
