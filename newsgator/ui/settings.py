"""Process-wide settings store backed by QSettings.

Exposes a single :class:`SettingsManager` singleton — widgets connect to its
:attr:`changed` signal to react to live updates (theme/font/size changes
from the Settings dialog), avoiding a restart.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal

from newsgator.ui.theme import (
    DEFAULT_FONT_FAMILY,
    DEFAULT_FONT_SIZE_PT,
    DEFAULT_THEME,
    ThemeName,
)

_KEY_THEME = "ui/theme"
_KEY_FONT_FAMILY = "ui/font_family"
_KEY_FONT_SIZE = "ui/font_size_pt"


class SettingsManager(QObject):
    """Reads and writes UI preferences. Emits :attr:`changed` on every save."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._store = QSettings()  # uses org/app name set on QApplication

    # --- accessors ----------------------------------------------------

    def theme(self) -> ThemeName:
        value = str(self._store.value(_KEY_THEME, DEFAULT_THEME))
        return value if value in ("light", "dark") else DEFAULT_THEME  # type: ignore[return-value]

    def font_family(self) -> str:
        return str(self._store.value(_KEY_FONT_FAMILY, DEFAULT_FONT_FAMILY))

    def font_size_pt(self) -> int:
        try:
            return int(self._store.value(_KEY_FONT_SIZE, DEFAULT_FONT_SIZE_PT))
        except (TypeError, ValueError):
            return DEFAULT_FONT_SIZE_PT

    # --- mutator ------------------------------------------------------

    def update(
        self,
        *,
        theme: ThemeName | None = None,
        font_family: str | None = None,
        font_size_pt: int | None = None,
    ) -> None:
        if theme is not None:
            self._store.setValue(_KEY_THEME, theme)
        if font_family is not None:
            self._store.setValue(_KEY_FONT_FAMILY, font_family)
        if font_size_pt is not None:
            self._store.setValue(_KEY_FONT_SIZE, int(font_size_pt))
        self._store.sync()
        self.changed.emit()


_instance: SettingsManager | None = None


def settings() -> SettingsManager:
    """Lazy singleton. Must be called after QApplication is constructed."""
    global _instance
    if _instance is None:
        _instance = SettingsManager()
    return _instance
