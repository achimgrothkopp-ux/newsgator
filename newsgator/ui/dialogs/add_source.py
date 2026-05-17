"""Modal dialog: add a new feed source to the local DB.

Pure-UI: the dialog only collects user input and validates the URL shape.
Persistence is the caller's job (MainWindow), so this widget stays unit-
testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass(slots=True, frozen=True)
class NewSourceSpec:
    feed_type: str
    url: str
    title: str
    category: str  # "" means "no category"


# (label shown to user, feed_type stored in DB)
FEED_TYPE_CHOICES: list[tuple[str, str]] = [
    ("RSS / Atom-Feed", "rss"),
    ("HTTP-Seite (Volltext)", "http"),
    ("YouTube-Kanal", "youtube"),
]


class AddSourceDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        existing_categories: Iterable[str] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neue Quelle hinzufügen")
        self.setMinimumWidth(440)
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self._type_combo = QComboBox()
        for label, value in FEED_TYPE_CHOICES:
            self._type_combo.addItem(label, value)
        form.addRow("Typ", self._type_combo)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://…")
        form.addRow("URL", self._url_edit)

        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("(leer = URL als Titel)")
        form.addRow("Titel", self._title_edit)

        self._category_combo = QComboBox()
        self._category_combo.setEditable(True)
        self._category_combo.addItem("")  # default: no category
        for cat in existing_categories:
            if cat and cat.strip():
                self._category_combo.addItem(cat)
        form.addRow("Kategorie", self._category_combo)

        layout.addLayout(form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setText("Hinzufügen")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._url_edit.textChanged.connect(self._update_ok_state)
        self._update_ok_state("")

    def values(self) -> NewSourceSpec:
        return NewSourceSpec(
            feed_type=self._type_combo.currentData(),
            url=self._url_edit.text().strip(),
            title=self._title_edit.text().strip(),
            category=self._category_combo.currentText().strip(),
        )

    def _update_ok_state(self, _text: str) -> None:
        url = self._url_edit.text().strip().lower()
        self._ok_button.setEnabled(url.startswith(("http://", "https://")))
