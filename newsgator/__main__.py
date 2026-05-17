"""Entry point: wires the Qt event loop into asyncio via qasync.

Started either with ``python -m newsgator`` or the ``newsgator`` console
script defined in pyproject.toml.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from newsgator.ui.main_window import MainWindow


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Newsgator")
    app.setOrganizationName("newsgator")

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
