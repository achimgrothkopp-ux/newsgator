# Changelog

Format orientiert an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/);
Versionierung folgt [SemVer](https://semver.org/lang/de/).

## [0.1.0] – 2026-05-18

Erste Vorabversion. Funktional vollständig gegen den v0.1-Plan
(Linux-Phase).

### Hinzugefügt
- Feed-Provider für RSS/Atom (feedparser), HTTP-Seiten (trafilatura)
  und YouTube-Kanäle/-Playlists (Kanal-RSS-URL).
- Async-Feed-Scheduler mit parallelem Sync und fehlertoleranter
  Provider-Ausführung; Hintergrund-Loop standardmäßig alle 15 Minuten.
- Qt-UI (PySide6 + qasync) mit Drei-Spalten-Layout:
  - Quellen-Sidebar mit Kategorie-Gruppierung, Kontextmenü
    (Bearbeiten/Löschen), virtuellem „Archiv"-Eintrag.
  - Artikel-Liste mit Custom-Delegate, Ungelesen-Indikator,
    Lesezeichen-Indikator für archivierte Artikel und Toolbar mit
    Filtern („Nur ungelesen", „Nur archiviert", Volltextsuche, debounced).
  - Vorschau-Pane mit Reader-Tab (QTextBrowser) und Webseite-Tab
    (QWebEngineView), Mark-as-Read beim Öffnen.
- Reader lädt eingebettete Bilder asynchron nach und skaliert sie auf
  die Viewport-Breite (kein horizontales Scrollen mehr).
- Artikel-Archivierung (Volltext via trafilatura, Offline-Lesen ohne
  Internet); togglebar per Ctrl+Shift+A.
- Quellen-Verwaltung: Add-/Edit-/Delete-Dialoge, Kategorien-Verwaltung,
  OPML-Import und -Export.
- Dark-/Light-Theme, einstellbare Font-Familie und -Größe.
- HTML-Export des aktuell angezeigten Artikels.
- SQLite-Schema mit `PRAGMA foreign_keys=ON` und Cascade-Delete; CLI
  (`scripts/cli.py`) mit `add` / `list` / `remove` / `sync` / `seed` /
  `cleanup` gegen die echte DB.
- Flatpak-Paketierung (KDE-6.7-Runtime + `io.qt.PySide.BaseApp//6.7`,
  AppStream-Metainfo, Build-Workflow inkl. Pip-Generator und
  Sdist→Wheel-Substituent).

### Bewusst nicht enthalten
- „Link teilen" — wandert in die geplante Android-App (Phase 2);
  auf dem Linux-Desktop kein Mehrwert gegenüber dem System-Share-Menü.

### Bekannte offene Punkte für Flathub-Submission
- App-Icon ist Platzhalter und sollte vor einer Flathub-Einreichung
  durch ein eigenes Mark ersetzt werden.
- Screenshot unter `flatpak/screenshots/main.png` fehlt noch (Pfad ist
  bereits im Metainfo verlinkt).

[0.1.0]: https://github.com/achimgrothkopp-ux/newsgator/releases/tag/v0.1.0
