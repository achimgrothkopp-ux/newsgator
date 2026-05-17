# Newsaggregator – Linux Desktop (Phase 1)

## Projektübersicht

Entwickle einen Newsaggregator für den Linux-Desktop. Die App aggregiert Inhalte aus RSS/Atom-Feeds,
HTTP-Quellen und YouTube-Kanälen, stellt sie in einer Qt-Oberfläche dar und bietet Archivierungs-
und Share-Funktionen. Dies ist Phase 1 (Linux); Phase 2 wird eine separate Android-App.

**Stack:** Python 3.12+, PySide6 (Qt6), asyncio + qasync, SQLite + SQLAlchemy, feedparser, httpx, trafilatura

---

## Architektur

Verwende eine klare **MVP-Struktur** (Model – View – Presenter):

```
newsaggregator/
├── main.py                  # Einstiegspunkt, qasync event loop setup
├── pyproject.toml
├── newsaggregator/
│   ├── __init__.py
│   ├── models/
│   │   ├── database.py      # SQLAlchemy engine, session factory
│   │   ├── source.py        # ORM-Modell: Feed-Quellen
│   │   └── article.py       # ORM-Modell: Artikel
│   ├── feeds/
│   │   ├── base.py          # Abstrakte FeedProvider-Klasse
│   │   ├── rss.py           # RSS/Atom via feedparser
│   │   ├── http.py          # HTTP-Scraper via httpx + trafilatura
│   │   └── youtube.py       # YouTube-Kanal-RSS oder Data API v3
│   ├── sync/
│   │   └── scheduler.py     # asyncio-basierter Hintergrund-Sync
│   ├── ui/
│   │   ├── main_window.py   # QMainWindow, 3-Panel-Layout
│   │   ├── source_panel.py  # QTreeWidget: Quellen-Sidebar
│   │   ├── article_list.py  # QListView + Custom Delegate
│   │   ├── article_view.py  # QWebEngineView / QTextBrowser
│   │   ├── dialogs/
│   │   │   └── add_source.py  # Dialog: Quelle hinzufügen
│   │   └── styles.py        # Qt-Stylesheets (Dark/Light)
│   └── utils/
│       ├── archive.py       # Lokales Speichern von Artikeln
│       └── share.py         # D-Bus / xdg-open / Zwischenablage
└── flatpak/
    └── org.newsaggregator.App.yaml
```

---

## Kritische Implementierungsdetails

### 1. asyncio + qasync Setup (main.py)

```python
import sys
import asyncio
from qasync import QEventLoop, asyncSlot
from PySide6.QtWidgets import QApplication
from newsaggregator.ui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()
```

**Wichtig:** Alle async-Methoden in Qt-Widgets mit `@asyncSlot()` dekorieren (nicht `@asyncio.coroutine`).
Niemals `asyncio.run()` verwenden – das zerstört den qasync event loop.

### 2. Feed-Sync Scheduler

```python
# sync/scheduler.py
import asyncio
import httpx
from newsaggregator.feeds.rss import RssFeedProvider
from newsaggregator.feeds.http import HttpFeedProvider
from newsaggregator.feeds.youtube import YoutubeFeedProvider

class FeedScheduler:
    def __init__(self, session_factory, interval_minutes=15):
        self.session_factory = session_factory
        self.interval = interval_minutes * 60
        self._task: asyncio.Task | None = None

    async def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _loop(self):
        while True:
            await self.sync_all()
            await asyncio.sleep(self.interval)

    async def sync_all(self):
        async with httpx.AsyncClient(timeout=10) as client:
            # Alle Quellen parallel abrufen
            async with self.session_factory() as session:
                sources = await session.execute(select(Source))
                tasks = [self._sync_one(client, src) for src in sources.scalars()]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                # Fehler loggen, nicht crashen
                for i, r in enumerate(results):
                    if isinstance(r, Exception):
                        logger.warning(f"Feed {i} fehlgeschlagen: {r}")
```

### 3. Datenbankschema (SQLAlchemy)

```python
# models/source.py
class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(unique=True)
    title: Mapped[str]
    feed_type: Mapped[str]  # "rss", "http", "youtube"
    category: Mapped[str | None]
    favicon_path: Mapped[str | None]
    last_synced: Mapped[datetime | None]
    articles: Mapped[list["Article"]] = relationship(back_populates="source")

# models/article.py
class Article(Base):
    __tablename__ = "articles"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    guid: Mapped[str] = mapped_column(unique=True)  # Verhindert Duplikate
    title: Mapped[str]
    url: Mapped[str]
    published_at: Mapped[datetime | None]
    summary: Mapped[str | None]
    content: Mapped[str | None]       # Volltext (wenn gescrapt)
    is_read: Mapped[bool] = mapped_column(default=False)
    is_archived: Mapped[bool] = mapped_column(default=False)
    archived_html: Mapped[str | None]  # Lokale Kopie
    source: Mapped["Source"] = relationship(back_populates="articles")
```

### 4. Qt UI – 3-Panel-Layout

```python
# ui/main_window.py
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Newsaggregator")
        self.resize(1200, 800)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.source_panel = SourcePanel()        # links, ~220px
        self.article_list = ArticleListWidget()  # mitte, ~380px
        self.article_view = ArticleView()        # rechts, Rest

        splitter.addWidget(self.source_panel)
        splitter.addWidget(self.article_list)
        splitter.addWidget(self.article_view)
        splitter.setSizes([220, 380, 600])
        self.setCentralWidget(splitter)

        # Signals verbinden
        self.source_panel.source_selected.connect(self.article_list.load_articles)
        self.article_list.article_selected.connect(self.article_view.show_article)

    @asyncSlot()
    async def refresh_all(self):
        await self.scheduler.sync_all()
        await self.article_list.reload()
```

### 5. Custom Article Delegate

```python
# ui/article_list.py
class ArticleDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        article = index.data(Qt.ItemDataRole.UserRole)
        # Ungelesen-Indikator: blauer Punkt links
        # Titel fett wenn ungelesen, normal wenn gelesen
        # Quelle + Datum darunter in grau
        # Favicon links neben Titel
        ...

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 72)  # Feste Zeilenhöhe
```

---

## Woche-für-Woche Anweisungen

### Woche 1 – Setup & Feed-Engine

1. `pyproject.toml` anlegen mit allen Dependencies:
   `pyside6`, `qasync`, `sqlalchemy[asyncio]`, `aiosqlite`, `feedparser`,
   `httpx`, `trafilatura`, `yt-dlp`

2. SQLAlchemy mit **async engine** aufsetzen:
   ```python
   engine = create_async_engine("sqlite+aiosqlite:///newsagg.db")
   ```

3. `RssFeedProvider` implementieren:
   - `feedparser.parse()` ist **synchron** – in `asyncio.to_thread()` wrappen!
   - Artikel-Duplikate per `guid`-Feld verhindern

4. `HttpFeedProvider` mit `trafilatura.fetch_url()` + `trafilatura.extract()`:
   - Ebenfalls synchron – in `asyncio.to_thread()` wrappen
   - Fallback: `httpx` direkt + BeautifulSoup für Metadaten

5. `YoutubeFeedProvider`:
   - Einfachste Methode: YouTube-Kanal-RSS-URL
     `https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID`
   - Kein API-Key nötig, feedparser kann das direkt parsen

### Woche 2 – Qt-Oberfläche

1. Zuerst `main.py` mit qasync-Loop zum Laufen bringen, dann UI schrittweise hinzufügen
2. `QTreeWidget` für Quellen-Sidebar: Kategorien als Top-Level, Quellen als Children
3. `QListView` mit `QStandardItemModel` für Artikel; Custom Delegate für das Rendering
4. Vorschau: `QTextBrowser` ist einfacher als `QWebEngineView` (kein extra Paket);
   `QWebEngineView` nur wenn JavaScript-Rendering der Quelle nötig
5. Alle DB-Zugriffe aus dem UI-Thread in `asyncio.create_task()` auslagern,
   niemals blocking DB-Calls im Haupt-Thread

### Woche 3 – Archiv & Share

1. **Archivierung:** Artikel-HTML via `trafilatura` extrahieren und in `archived_html`-Feld speichern.
   Optional: Bilder lokal in `~/.local/share/newsaggregator/cache/` cachen.

2. **Share-Funktion:**
   ```python
   # utils/share.py
   import subprocess
   from PySide6.QtWidgets import QApplication

   def copy_to_clipboard(text: str):
       QApplication.clipboard().setText(text)

   def open_in_browser(url: str):
       subprocess.Popen(["xdg-open", url])
   ```

3. Suchfunktion: SQLite Full-Text-Search (FTS5) für Artikel-Titel und -Inhalt aktivieren

### Woche 4 – Paketierung & Polish

1. **Dark/Light-Mode:** Qt-eigenes `QStyleFactory` nutzen oder `qt-material` für schnelles Theming
2. **Tastaturkürzel:**
   - `j` / `k` → nächster / vorheriger Artikel
   - `r` → Refresh
   - `a` → Archivieren
   - `o` → Im Browser öffnen
3. **Flatpak-Manifest** (`flatpak/org.newsaggregator.App.yaml`):
   - Base-image: `org.freedesktop.Platform//23.08`
   - Python-Dependencies als Flatpak-Modules oder über pip im Build-Step
4. **AppImage** als einfacher Fallback mit `python-appimage`

---

## Häufige Fallstricke

| Problem | Lösung |
|---|---|
| `feedparser.parse()` blockiert den Event Loop | In `asyncio.to_thread()` wrappen |
| Qt-Widgets aus asyncio-Tasks updaten | Nur über Signals/Slots, nie direkt |
| SQLAlchemy Session nicht thread-safe | Immer `async with session_factory()` pro Request |
| `QWebEngineView` fehlt | `pip install pyside6-addons` oder auf `QTextBrowser` ausweichen |
| YouTube ohne API-Key | Kanal-RSS-URL verwenden statt Data API |
| Doppelte Artikel beim Sync | `guid`-Feld in DB als UNIQUE, INSERT OR IGNORE |

---

## Abhängigkeiten (pyproject.toml)

```toml
[project]
name = "newsaggregator"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pyside6>=6.7",
    "qasync>=0.27",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "feedparser>=6.0",
    "httpx>=0.27",
    "trafilatura>=1.12",
    "yt-dlp>=2024.1",
]

[project.optional-dependencies]
dev = ["ruff", "mypy", "pytest", "pytest-asyncio"]
```

---

## Ziel: v0.1 Release

- [ ] RSS/Atom/YouTube-Feeds abrufbar und dargestellt
- [ ] 3-Panel-UI funktionsfähig
- [ ] Hintergrund-Sync alle 15 Minuten
- [ ] Archivieren und Lesen ohne Internet
- [ ] Link teilen / in Browser öffnen
- [ ] Flatpak oder AppImage paketiert
