"""Entry point: wires the Qt event loop into asyncio via qasync."""

from __future__ import annotations

import asyncio
import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from newsgator.models.database import get_session_factory, init_db
from newsgator.ui.main_window import MainWindow


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # QtWebEngine requires shared OpenGL contexts and must be set before
    # the QApplication is instantiated.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setApplicationName("Newsgator")
    app.setOrganizationName("newsgator")

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    session_factory = get_session_factory()
    window = MainWindow(session_factory)
    window.show()

    async def _startup() -> None:
        await init_db()
        await window.refresh()
        await window.start_background_sync()

    # Cancel the scheduler task as the app starts tearing down; the qasync
    # loop is still spinning at this point so the cancellation actually
    # reaches the task before the loop is closed.
    app.aboutToQuit.connect(
        lambda: asyncio.ensure_future(window.stop_background_sync())
    )

    with loop:
        loop.create_task(_startup())
        loop.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
