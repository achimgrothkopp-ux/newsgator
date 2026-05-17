"""Settings dialog: theme, font family, font size.

The dialog edits a local copy and only commits to :func:`settings` on OK,
so Cancel discards everything.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from newsgator.ui.settings import settings


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(380)
        self.setModal(True)

        s = settings()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self._theme_combo = QComboBox()
        self._theme_combo.addItem("Hell", "light")
        self._theme_combo.addItem("Dunkel", "dark")
        idx = self._theme_combo.findData(s.theme())
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        form.addRow("Farbschema", self._theme_combo)

        self._font_combo = QFontComboBox()
        current_family = s.font_family().split(",", 1)[0].strip().strip("'\"")
        self._font_combo.setCurrentFont(QFont(current_family))
        form.addRow("Schriftart", self._font_combo)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(8, 24)
        self._size_spin.setSuffix(" pt")
        self._size_spin.setValue(s.font_size_pt())
        form.addRow("Schriftgrad", self._size_spin)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Übernehmen")
        buttons.accepted.connect(self._commit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _commit(self) -> None:
        settings().update(
            theme=self._theme_combo.currentData(),
            font_family=self._font_combo.currentFont().family(),
            font_size_pt=self._size_spin.value(),
        )
        self.accept()
