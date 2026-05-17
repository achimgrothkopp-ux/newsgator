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
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QPushButton,
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
        *,
        initial: NewSourceSpec | None = None,
    ) -> None:
        super().__init__(parent)
        self._edit_mode = initial is not None
        self.setWindowTitle(
            "Quelle bearbeiten" if self._edit_mode else "Neue Quelle hinzufügen"
        )
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

        # ComboBox + "+" button on the same row so the user can spin up a
        # brand-new category without leaving the dialog.
        cat_row = QWidget()
        cat_layout = QHBoxLayout(cat_row)
        cat_layout.setContentsMargins(0, 0, 0, 0)
        cat_layout.setSpacing(6)
        cat_layout.addWidget(self._category_combo, 1)
        self._new_cat_button = QPushButton("+")
        self._new_cat_button.setFixedWidth(28)
        self._new_cat_button.setToolTip("Neue Kategorie anlegen")
        self._new_cat_button.clicked.connect(self._on_new_category)
        cat_layout.addWidget(self._new_cat_button)
        form.addRow("Kategorie", cat_row)

        layout.addLayout(form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setText("Speichern" if self._edit_mode else "Hinzufügen")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self._url_edit.textChanged.connect(self._update_ok_state)

        if initial is not None:
            type_idx = self._type_combo.findData(initial.feed_type)
            if type_idx >= 0:
                self._type_combo.setCurrentIndex(type_idx)
            self._url_edit.setText(initial.url)
            self._title_edit.setText(initial.title)
            if initial.category:
                if self._category_combo.findText(initial.category) < 0:
                    self._category_combo.addItem(initial.category)
                self._category_combo.setCurrentText(initial.category)

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

    def _on_new_category(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Neue Kategorie", "Name der Kategorie:"
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        # Add to the dropdown if it isn't there already, then select it.
        if self._category_combo.findText(name) < 0:
            self._category_combo.addItem(name)
        self._category_combo.setCurrentText(name)
