#!/usr/bin/env python3
"""Post-process python-deps.yaml: replace sdist URLs with cp311 manylinux
wheels where they exist on PyPI.

flatpak-pip-generator's --runtime mode (the canonical way to pick correct
platform wheels) fails on KDE Sdk 6.7 because the SDK ships no `packaging`
module, so it falls back to picking sdists. Building those sdists in-sandbox
trips on setuptools version skew — old setuptools doesn't understand PEP 639
SPDX license strings (regex, …), new setuptools doesn't accept some older
license dicts (greenlet 3.5, …). Wheels sidestep the whole mess.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

PY_TAG = "cp311"
ARCH = "x86_64"
SDIST_RE = re.compile(r"/([A-Za-z0-9_.]+)-([0-9][^/]*?)\.tar\.gz$")


def find_wheel(pkg: str, ver: str) -> tuple[str, str] | None:
    try:
        with urllib.request.urlopen(
            f"https://pypi.org/pypi/{pkg}/{ver}/json", timeout=15
        ) as r:
            meta = json.load(r)
    except Exception as exc:
        print(f"  ! {pkg} {ver}: pypi lookup failed ({exc})")
        return None

    cp311_specific: list[dict] = []
    abi3: list[dict] = []
    for entry in meta["urls"]:
        if entry["packagetype"] != "bdist_wheel":
            continue
        name = entry["filename"]
        if "manylinux" not in name or ARCH not in name:
            continue
        if f"-{PY_TAG}-" in name:
            cp311_specific.append(entry)
        elif "-abi3-" in name and "-cp3" in name:
            abi3.append(entry)

    chosen = (cp311_specific or abi3)[:1]
    if not chosen:
        return None
    e = chosen[0]
    return e["url"], e["digests"]["sha256"]


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "python-deps.yaml")
    data = yaml.safe_load(path.read_text())

    swapped = 0
    skipped = 0
    for module in data.get("modules", []):
        for source in module.get("sources", []):
            if not isinstance(source, dict):
                continue
            url = source.get("url", "")
            m = SDIST_RE.search(url)
            if not m:
                continue
            pkg = m.group(1).replace("_", "-").lower()
            ver = m.group(2)
            result = find_wheel(pkg, ver)
            if result is None:
                print(f"  · {pkg} {ver}: keeping sdist (no matching wheel)")
                skipped += 1
                continue
            new_url, new_sha = result
            print(f"  → {pkg} {ver}: swapped for wheel")
            source["url"] = new_url
            source["sha256"] = new_sha
            swapped += 1

    path.write_text(yaml.safe_dump(data, sort_keys=False))
    print(f"\nswapped {swapped} sdists → wheels, kept {skipped} as sdist")
    return 0


if __name__ == "__main__":
    sys.exit(main())
