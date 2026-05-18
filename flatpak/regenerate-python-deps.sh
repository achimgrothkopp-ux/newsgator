#!/usr/bin/env bash
# Regenerate flatpak/python-deps.yaml from flatpak/requirements.txt.
#
# flatpak-pip-generator resolves the full transitive dep tree, downloads each
# wheel/sdist, and writes a YAML module with pinned URLs + SHA256 hashes.
# That output is what the Flatpak build actually consumes — Flathub builders
# disable network access, so deps must be fetchable through Flatpak's source
# system (which honors the pinned URLs).
#
# Re-run this whenever pyproject.toml's [project.dependencies] changes.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GENERATOR="${HERE}/.flatpak-pip-generator.py"
GENERATOR_URL="https://raw.githubusercontent.com/flatpak/flatpak-builder-tools/master/pip/flatpak-pip-generator.py"
VENV="${HERE}/.pip-gen-venv"

if [[ ! -f "${GENERATOR}" ]]; then
  echo "→ fetching flatpak-pip-generator…"
  curl -L --fail -o "${GENERATOR}" "${GENERATOR_URL}"
fi

# The generator itself needs requirements-parser + packaging. Keep them in a
# throwaway venv so we don't pollute the project .venv.
if [[ ! -d "${VENV}" ]]; then
  echo "→ creating helper venv for the generator…"
  python3 -m venv "${VENV}"
  "${VENV}/bin/pip" install --quiet --upgrade pip
  "${VENV}/bin/pip" install --quiet \
    'requirements-parser>=0.11,<1.0' \
    'packaging>=23.0' \
    PyYAML \
    aiohttp \
    toml
fi

cd "${HERE}"
"${VENV}/bin/python" "${GENERATOR}" \
  --yaml \
  --output python-deps \
  --requirements-file requirements.txt

echo "→ swapping sdists for cp311 manylinux wheels where possible…"
"${VENV}/bin/python" "${HERE}/swap-sdists-for-wheels.py" "${HERE}/python-deps.yaml"

echo "→ wrote ${HERE}/python-deps.yaml"
