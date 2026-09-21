#!/usr/bin/env python3
"""Copy a locally maintained, authorized Tizen Live mapping into the WGT.

Input and output are deliberately ignored by Git.  Only direct HLS, DASH or
progressive HTTPS/HTTP endpoints are accepted: this is a configuration bridge,
not a scraper, resolver, or credential extractor.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "private_iptv" / "tizen_authorized_live.json"
DEFAULT_OUTPUT = ROOT / "tizen" / "PrippiStreamTV" / "data" / "authorized_live.json"
ROWS = {"tv", "sky", "sport", "calcio", "cinema", "dazn", "documentari", "intrattenimento"}
MANIFEST = re.compile(r"\.(?:m3u8|mpd|mp4|webm)(?:\?|$)", re.I)


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    payload = json.loads(source.read_text(encoding="utf-8"))
    accepted: list[dict] = []
    skipped = 0
    for channel in payload.get("channels", payload.get("items", [])):
        row = str(channel.get("row") or channel.get("live_row") or "").lower()
        title = str(channel.get("title") or channel.get("fulltitle") or "").strip()
        sources = []
        for item in channel.get("sources", [channel]):
            url = str(item.get("url") or "").strip()
            if not re.match(r"^https?://", url, re.I) or not MANIFEST.search(url):
                continue
            source_entry = {key: item[key] for key in (
                "url", "manifest_type", "type", "headers", "drm_type", "drm",
                "license_key", "license_url", "license_headers", "subtitles"
            ) if key in item}
            sources.append(source_entry)
        if row not in ROWS or not title or not sources:
            skipped += 1
            continue
        accepted.append({
            "row": row, "title": title, "logo": str(channel.get("logo") or ""),
            "thumbnail": str(channel.get("thumbnail") or ""), "plot": str(channel.get("plot") or ""),
            "sources": sources,
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"version": 1, "channels": accepted}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Tizen authorized Live: {len(accepted)} canali pronti, {skipped} ignorati (endpoint non diretti o incompleti).")


if __name__ == "__main__":
    main()
