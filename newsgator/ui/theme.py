"""Centralised color/font palette plus stylesheet generators.

Two themes ship today — ``light`` (black on white, gray selection) and
``dark``. Anything that paints custom colors (the article list delegate,
the article view HTML renderer) should read from :func:`current_palette`
so a theme switch can take effect without restarting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtGui import QColor

ThemeName = Literal["light", "dark"]


@dataclass(slots=True, frozen=True)
class ThemePalette:
    name: ThemeName
    bg: str
    fg: str
    fg_muted: str
    fg_dim: str
    selection_bg: str
    selection_fg: str
    separator: str
    accent: str  # the unread-dot blue / link color
    statusbar_bg: str
    statusbar_fg: str
    splitter_handle: str


LIGHT = ThemePalette(
    name="light",
    bg="#ffffff",
    fg="#000000",
    fg_muted="#6b7280",
    fg_dim="#9ca3af",
    selection_bg="#e5e7eb",
    selection_fg="#000000",
    separator="#e5e7eb",
    accent="#2563eb",
    statusbar_bg="#f9fafb",
    statusbar_fg="#374151",
    splitter_handle="#e5e7eb",
)

DARK = ThemePalette(
    name="dark",
    bg="#1f2226",
    fg="#e5e7eb",
    fg_muted="#9ca3af",
    fg_dim="#6b7280",
    selection_bg="#374151",
    selection_fg="#ffffff",
    separator="#2d3138",
    accent="#60a5fa",
    statusbar_bg="#181a1d",
    statusbar_fg="#9ca3af",
    splitter_handle="#2d3138",
)

PALETTES: dict[str, ThemePalette] = {"light": LIGHT, "dark": DARK}

DEFAULT_FONT_FAMILY = "Inter, -apple-system, system-ui, sans-serif"
DEFAULT_FONT_SIZE_PT = 10
DEFAULT_THEME: ThemeName = "light"


def palette_for(name: str) -> ThemePalette:
    return PALETTES.get(name, LIGHT)


def build_stylesheet(p: ThemePalette, *, font_family: str, font_size_pt: int) -> str:
    """Generate the QApplication-wide stylesheet for a given palette/font."""
    # Use the first family in a comma-separated list for Qt widgets (Qt's QSS
    # font-family doesn't do fallback the way CSS does).
    qt_font = font_family.split(",", 1)[0].strip().strip("'\"")
    return f"""
QMainWindow, QWidget {{
    background-color: {p.bg};
    color: {p.fg};
    font-family: "{qt_font}";
    font-size: {font_size_pt}pt;
}}
QTreeWidget, QListView, QTextBrowser {{
    background-color: {p.bg};
    color: {p.fg};
    border: none;
}}
QTreeWidget::item:selected, QListView::item:selected {{
    background-color: {p.selection_bg};
    color: {p.selection_fg};
}}
QSplitter::handle {{ background-color: {p.splitter_handle}; }}
QStatusBar {{ background-color: {p.statusbar_bg}; color: {p.statusbar_fg}; }}
QMenuBar {{ background-color: {p.bg}; color: {p.fg}; }}
QMenuBar::item:selected {{ background-color: {p.selection_bg}; }}
QMenu {{ background-color: {p.bg}; color: {p.fg}; }}
QMenu::item:selected {{ background-color: {p.selection_bg}; color: {p.selection_fg}; }}
QLineEdit, QComboBox, QSpinBox {{
    background-color: {p.bg};
    color: {p.fg};
    border: 1px solid {p.separator};
    padding: 2px 4px;
}}
QPushButton {{
    background-color: {p.bg};
    color: {p.fg};
    border: 1px solid {p.separator};
    padding: 4px 10px;
}}
QPushButton:hover {{ background-color: {p.selection_bg}; }}
"""


def qcolor(hex_string: str) -> QColor:
    return QColor(hex_string)
