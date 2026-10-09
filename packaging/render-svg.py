#!/usr/bin/env python3
"""Rasterise an SVG through Qt.

ImageMagick's built-in MSVG renderer mangles text (it drops kerning and
mis-handles letter-spacing), which is visible the moment the SVG carries a
wordmark. Qt uses the same renderer the app ships, so what we rasterise matches
what a user sees.
"""

import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtSvg, QtWidgets


def render(svg: Path, png: Path, width: int, height: int) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    renderer = QtSvg.QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise SystemExit(f"invalid SVG: {svg}")

    # Render at 2x and downsample: text hinting at 1x produces thin, aliased
    # strokes that look bad in a README rendered at half width.
    scale = 2
    image = QtGui.QImage(width * scale, height * scale, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
    renderer.render(painter)
    painter.end()

    image.scaled(
        width,
        height,
        QtCore.Qt.KeepAspectRatio,
        QtCore.Qt.SmoothTransformation,
    ).save(str(png))
    print(f"  {png}  {width}x{height}")


if __name__ == "__main__":
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    w = int(sys.argv[3]) if len(sys.argv) > 3 else 1280
    h = int(sys.argv[4]) if len(sys.argv) > 4 else 400
    render(src, dst, w, h)
