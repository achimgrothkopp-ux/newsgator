"""Headless smoke test: launch MainWindow, close it after 500 ms.

Verifies that qasync wires up correctly, all imports load, and the layout
builds without errors — without needing a real display. Run with:

    QT_QPA_PLATFORM=offscreen .venv/bin/python -m scripts.check_window
"""

from __future__ import annotations

import asyncio
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from newsgator.ui.main_window import MainWindow


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    sizes = window.centralWidget().sizes()
    print(f"window title:   {window.windowTitle()}")
    print(f"window size:    {window.size().width()}x{window.size().height()}")
    print(f"splitter sizes: {sizes}  (expected ~[220, 380, 600] until layout settles)")

    # Close shortly after the loop starts.
    QTimer.singleShot(500, app.quit)

    with loop:
        loop.run_forever()
    print("OK — window opened and closed cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
