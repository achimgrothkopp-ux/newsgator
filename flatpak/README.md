# Flatpak-Paketierung

Manifest und Hilfsdateien um Newsgator als Flatpak zu bauen
(lokal und Flathub-tauglich).

## App-ID

`io.github.achimgrothkopp_ux.Newsgator` — GitHub-Fallback-ID, weil keine
eigene Domain. Unterstrich, weil der GitHub-Username einen Bindestrich
enthält (in Flatpak-App-IDs nicht erlaubt).

## Dateien

| Datei | Zweck |
|---|---|
| `io.github.achimgrothkopp_ux.Newsgator.yaml` | Flatpak-Manifest |
| `io.github.achimgrothkopp_ux.Newsgator.desktop` | XDG-Desktop-Eintrag |
| `io.github.achimgrothkopp_ux.Newsgator.metainfo.xml` | AppStream-Metainfo (für Software-Center) |
| `icons/io.github.achimgrothkopp_ux.Newsgator.svg` | App-Icon (Platzhalter, **muss vor Flathub-Submission ersetzt werden**) |
| `requirements.txt` | Spiegel der pyproject-Dependencies, Input für den Pip-Generator |
| `regenerate-python-deps.sh` | Skript, das `flatpak-pip-generator` aufruft und `python-deps.yaml` schreibt |
| `python-deps.yaml` | **Generiert** — pinnte Wheel-URLs + Hashes für reproducible Builds |

## Voraussetzungen

```sh
sudo apt install flatpak flatpak-builder
flatpak remote-add --if-not-exists --user flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub \
  org.kde.Platform//6.7 \
  org.kde.Sdk//6.7 \
  io.qt.PySide.BaseApp//6.7
```

PySide6 kommt über die BaseApp `io.qt.PySide.BaseApp` rein — der pip-Wheel
würde sein eigenes Qt mitbringen und mit dem Runtime-Qt kollidieren.

## Build-Workflow

```sh
# 1) Einmalig (und nach jedem pyproject-dep-Update):
./flatpak/regenerate-python-deps.sh

# 2) Bauen:
flatpak-builder --user --install --force-clean build \
  flatpak/io.github.achimgrothkopp_ux.Newsgator.yaml

# 3) Starten:
flatpak run io.github.achimgrothkopp_ux.Newsgator
```

## Vor Flathub-Submission noch erledigen

- App-Icon mit eigenem Design ersetzen (`icons/*.svg`); idealerweise auch
  256×256-PNG-Variante.
- Mindestens einen echten Screenshot unter `screenshots/main.png` einchecken
  und im `metainfo.xml`-Pfad referenzieren.
- `python-deps.yaml` committen.
- `flathub-builder --keep-build-dirs` + `flatpak run --command=appstream-util io.flathub.AppStream validate-relax …` durchlaufen lassen.
- Bei Flathub das Repo unter <https://github.com/flathub/flathub> per PR
  einreichen.
