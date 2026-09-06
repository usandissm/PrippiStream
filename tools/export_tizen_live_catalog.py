#!/usr/bin/env python3
"""Esporta il catalogo Live ufficiale Android in un asset statico Tizen.

Lo script viene eseguito soltanto in fase di sviluppo: la TV legge il JSON
incorporato nel bundle OTA e non avvia Python né contatta un gateway locale.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT.parent / "PrippiStreamApp"
PYTHON_ROOT = ANDROID / "app" / "src" / "main" / "python"
LOGO_ROOT = (
    ANDROID
    / "app"
    / "src"
    / "main"
    / "assets"
    / "pydata"
    / "resources"
    / "media"
    / "tv_logos"
)
SPORT_LOGO_ROOT = (
    ANDROID
    / "app"
    / "src"
    / "main"
    / "assets"
    / "pydata"
    / "resources"
    / "media"
    / "sport_posters"
)
OUT = ROOT / "tizen" / "PrippiStreamTV" / "data" / "live_channels.json"
OUT_LOGOS = ROOT / "tizen" / "PrippiStreamTV" / "assets" / "tv_logos"


def clean_title(value: object) -> str:
    return re.sub(r"\[(?:/?B|/?I|/?COLOR[^]]*)\]", "", str(value or ""), flags=re.I).strip()


def logo_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def main() -> None:
    if not PYTHON_ROOT.is_dir():
        raise SystemExit(f"Repository Android non trovato: {ANDROID}")

    sys.path.insert(0, str(PYTHON_ROOT))
    import bridge  # type: ignore  # noqa: PLC0415

    bridge.init()
    from platformcode import sportchannels, tvchannels  # type: ignore  # noqa: PLC0415

    channels = []
    daddy_tv_by_title = {
        clean_title(info.get("name")).lower(): channel_id
        for channel_id, info in sportchannels._DADDY.items()
        if info.get("row") == "tv"
    }
    for item in tvchannels.load():
        raw = vars(item)
        title = clean_title(raw.get("fulltitle") or raw.get("title"))
        if not title:
            continue
        slug = "rai_sport" if title.lower().startswith("raiplay sport ") else logo_slug(title)
        logo = f"{slug}.png" if (LOGO_ROOT / f"{slug}.png").is_file() else ""
        channels.append(
            {
                "channel": str(raw.get("channel") or ""),
                "title": title,
                "fulltitle": title,
                "contentType": "video",
                "action": "findvideos",
                "url": str(raw.get("url") or ""),
                "video_url": str(raw.get("video_url") or ""),
                "callSign": str(raw.get("callSign") or ""),
                "id": str(raw.get("id") or ""),
                "plot": clean_title(raw.get("plot")),
                "logo": logo,
                "thumbnail": str(raw.get("thumbnail") or ""),
                "is_live_channel": True,
                "isLive": True,
                "live_row": "tv",
                "daddy_code": daddy_tv_by_title.get(title.lower(), ""),
            }
        )

    premium_rows = (
        ("sky", list(sportchannels.CINEMA_CANDIDATES) + list(sportchannels.DEFAULT_SKY)),
        ("sport", list(sportchannels.DEFAULT_SPORT)),
    )
    for row_key, entries in premium_rows:
        for entry in entries:
            title = clean_title(entry.get("title"))
            par = str(entry.get("par") or "")
            poster_name = par.replace("+", "plus").replace(" ", "_") + ".png"
            logo = poster_name if (SPORT_LOGO_ROOT / poster_name).is_file() else ""
            channels.append(
                {
                    "channel": "sportchannels",
                    "title": title,
                    "fulltitle": title,
                    "contentType": "video",
                    "action": "live_channel",
                    "url": "",
                    "plot": "",
                    "logo": logo,
                    "thumbnail": "",
                    "is_live_channel": True,
                    "isLive": True,
                    "live_row": row_key,
                    "sport_kind": str(entry.get("kind") or ""),
                    "sport_par": par,
                    "sport_fs": entry.get("fs"),
                    "daddy_code": sportchannels._DADDY_FALLBACK.get(par, ""),
                }
            )

        existing = {str(entry.get("sport_par") or "") for entry in channels if entry.get("live_row") == row_key}
        for channel_id, info in sportchannels._DADDY.items():
            if info.get("row") != row_key or info.get("alias") or channel_id in existing:
                continue
            poster_name = channel_id + ".png"
            channels.append(
                {
                    "channel": "sportchannels",
                    "title": clean_title(info.get("name")),
                    "fulltitle": clean_title(info.get("name")),
                    "contentType": "video",
                    "action": "live_channel",
                    "url": "",
                    "plot": "",
                    "logo": poster_name if (SPORT_LOGO_ROOT / poster_name).is_file() else "",
                    "thumbnail": "",
                    "is_live_channel": True,
                    "isLive": True,
                    "live_row": row_key,
                    "sport_kind": "daddy",
                    "sport_par": channel_id,
                    "sport_fs": None,
                    "daddy_code": channel_id,
                }
            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(channels, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    OUT_LOGOS.mkdir(parents=True, exist_ok=True)
    copied = 0
    for logo in sorted({entry["logo"] for entry in channels if entry["logo"]}):
        source = SPORT_LOGO_ROOT / logo
        if not source.is_file():
            source = LOGO_ROOT / logo
        shutil.copy2(source, OUT_LOGOS / logo)
        copied += 1
    print(f"Tizen Live: {len(channels)} canali, {copied} loghi -> {OUT}")


if __name__ == "__main__":
    main()
