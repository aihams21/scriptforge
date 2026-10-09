#!/usr/bin/env python3
"""Record the app turning a raw script into a form, and encode it as a GIF.

Frames come from the real Qt window under the offscreen platform plugin, so the
demo cannot drift from the product: if the layout breaks, this script breaks.

Deliberately short (~10s) and one-shot, because a demo loop that lingers on an
idle screen reads as "nothing happens".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scriptforge.gui.main_window import MainWindow  # noqa: E402

W, H = 900, 520
FPS = 20

DEMO_SCRIPT = """#!/bin/bash
# port-check.sh — no arguments, no help text, questions only
echo "== netcheck =="
read -rp "target host: " host
read -rp "port [443]: " port
case "$port" in
  22|80|443) ;;
  *) echo "unusual port" ;;
esac
read -rp "resolve DNS first? [y/N] " dns
echo "connecting to $host:$port"
"""


def pump(ms: int) -> None:
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


def grab(window, steps: list, hold: int) -> None:
    """Record one step, extended by `hold` ticks if the window has not changed.

    Repeating a frame N times instead of giving it a longer delay is what turns
    an 11-second demo into a 6.7 MB GIF: a static screen re-encoded N times
    costs N frames and compresses to nothing.
    """

    image = window.grab()
    image = image.scaled(W, H, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)

    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    key = hash(bytes(buffer.data()))
    if steps and steps[-1][0] == key:
        steps[-1][1] += hold
        return
    steps.append([key, hold, image])


def type_into(window, var: str, value) -> None:
    field = window.interface.inputs.get(var)
    if field is None:
        return
    if isinstance(field, QtWidgets.QCheckBox):
        field.setChecked(bool(value))
    else:
        field.setText(str(value))


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/demo.gif")
    out.parent.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="sf-demo-"))
    try:
        script = tmp / "port-check.sh"
        script.write_text(DEMO_SCRIPT)
        script.chmod(0o755)

        app = QtWidgets.QApplication([])
        window = MainWindow(roots=[tmp], lang="en")
        window.resize(W, H)
        window.show()
        pump(320)
        window.rescan()
        pump(200)

        steps: list = []

        # 1. the bare script, sitting in the list
        grab(window, steps, 22)

        # 2. select it
        window.sidebar.list.setCurrentRow(0)
        pump(220)
        grab(window, steps, 20)

        # 3. the generated interface
        window.tabs.setCurrentWidget(window.interface)
        pump(260)
        grab(window, steps, 26)

        # 4. fill it in
        type_into(window, "host", "10.0.0.5")
        pump(110)
        type_into(window, "port", "8443")
        pump(110)
        # The third prompt has to be answered too: the child blocks on an
        # unanswered read and the worker thread outlives the recording.
        type_into(window, "dns", True)
        pump(140)
        grab(window, steps, 26)

        # 5. run it
        window.on_run()
        pump(700)
        window.tabs.setCurrentWidget(window.run_panel)
        grab(window, steps, 34)

        # 6. output lands
        pump(900)
        grab(window, steps, 44)

        # 7. arabic, same window
        window.toggle_language()
        window.tabs.setCurrentWidget(window.interface)
        pump(300)
        grab(window, steps, 30)

        window.toggle_language()
        window.tabs.setCurrentWidget(window.overview)
        pump(260)
        grab(window, steps, 30)

        # QThread aborts the interpreter if it is still running at teardown.
        deadline = QtCore.QElapsedTimer()
        deadline.start()
        while window._thread is not None and deadline.elapsed() < 8000:
            pump(80)
        if window._thread is not None:
            window.on_stop()
        window.close()
        window.deleteLater()
        pump(60)

        if not (shutil.which("convert") or shutil.which("magick")):
            print("ImageMagick is required to encode the GIF", file=sys.stderr)
            return 2

        raw = tmp / "frames"
        raw.mkdir()

        # One output frame per visual change, each carrying the accumulated
        # delay of the ticks it stood still for.
        delays: list[int] = []
        for _, ticks, image in steps:
            image.save(str(raw / f"{len(delays):04d}.png"))
            delays.append(max(2, round(ticks * 100 / FPS)))

        pngs = sorted(str(p) for p in raw.glob("*.png"))
        binary = shutil.which("magick") or shutil.which("convert")

        cmd = [binary, "-loop", "0"]
        for png, delay in zip(pngs, delays):
            cmd += ["-delay", str(delay), png]
        # No -layers OptimizeTransparency: on frames differing only in a text
        # region it flattened each one to a 374-byte blank.
        cmd += ["-colors", "64", "-dither", "FloydSteinberg", str(out)]
        subprocess.run(cmd, check=True)

        size_kb = out.stat().st_size / 1024
        print(f"  {out}  {len(pngs)} frames  {sum(delays)/100:.1f}s  {size_kb:.0f} KB")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())