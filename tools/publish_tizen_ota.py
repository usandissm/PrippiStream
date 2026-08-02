#!/usr/bin/env python3
"""Genera il canale OTA Tizen firmato con hash SHA-256."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "tizen" / "PrippiStreamTV"
OUT = ROOT / "docs" / "tizen" / "app"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not match:
        raise RuntimeError(f"Impossibile estrarre {label}")
    return match.group(1).strip() + "\n"


def main() -> None:
    version_info = json.loads(read(APP / "ota-version.json"))
    index = read(APP / "index.html")
    body = extract(r"<body[^>]*>(.*?)</body>", index, "body HTML")
    inline_styles = re.findall(r"<style[^>]*>(.*?)</style>", index, re.IGNORECASE | re.DOTALL)
    css = read(APP / "css" / "style.css").rstrip() + "\n\n" + "\n\n".join(
        style.strip() for style in inline_styles
    ) + "\n"
    js = read(APP / "main.js")

    files = {"html": body, "css": css, "js": js}
    names = {"html": "app.html", "css": "app.css", "js": "app.js"}
    OUT.mkdir(parents=True, exist_ok=True)
    for key, content in files.items():
        (OUT / names[key]).write_text(content, encoding="utf-8", newline="\n")

    manifest = {
        "schema": 1,
        "channel": "stable",
        "version": str(version_info["version"]),
        "revision": int(version_info["revision"]),
        "published_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": {
            key: {"url": names[key], "sha256": sha256(content)}
            for key, content in files.items()
        },
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Tizen OTA {manifest['version']} rev.{manifest['revision']} -> {OUT}")


if __name__ == "__main__":
    main()
