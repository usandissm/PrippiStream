#!/usr/bin/env python3
"""Sincronizza in modo controllato il motore PrippiStream-v2 nell'APK.

Senza opzioni mostra il piano senza modificare file. ``--check`` restituisce
exit code 1 quando la copia APK diverge dalla sorgente. ``--apply`` applica il
piano e registra versione/commit della sorgente.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, Mapping


APP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = Path(__file__).with_name("engine_sync_manifest.json")


@dataclass(frozen=True)
class ChangeSet:
    added: tuple[str, ...]
    updated: tuple[str, ...]
    deleted: tuple[str, ...]
    unchanged: int

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.updated or self.deleted)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fallisce se esistono divergenze")
    mode.add_argument("--apply", action="store_true", help="applica la sincronizzazione")
    parser.add_argument("--source", type=Path, help="root alternativa di PrippiStream-v2")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--verbose", action="store_true", help="elenca ogni file divergente")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="consente --apply anche con modifiche Git non committate nella sorgente",
    )
    return parser.parse_args()


def load_manifest(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("schema_version") != 1:
        raise ValueError("schema manifest non supportato")
    return manifest


def excluded(path: Path, rules: Mapping[str, Iterable[str]]) -> bool:
    if PurePosixPath(path).as_posix() in set(rules.get("paths", [])):
        return True
    if any(part in set(rules["directory_names"]) for part in path.parts[:-1]):
        return True
    if path.name in set(rules["file_names"]):
        return True
    return path.suffix.lower() in set(rules["suffixes"])


def add_file(files: Dict[str, Path], source_root: Path, relative: str, rules: dict) -> None:
    rel = Path(relative)
    source = source_root / rel
    if not source.is_file():
        raise FileNotFoundError(f"file previsto non trovato: {source}")
    if not excluded(rel, rules):
        files[PurePosixPath(rel).as_posix()] = source


def collect_engine(source_root: Path, config: dict, rules: dict) -> Dict[str, Path]:
    files: Dict[str, Path] = {}
    for relative in config["files"]:
        add_file(files, source_root, relative, rules)
    for directory in config["directories"]:
        base = source_root / directory
        if not base.is_dir():
            raise FileNotFoundError(f"directory prevista non trovata: {base}")
        for source in sorted(p for p in base.rglob("*") if p.is_file()):
            rel = source.relative_to(source_root)
            if not excluded(rel, rules):
                files[PurePosixPath(rel).as_posix()] = source
    return files


def collect_assets(source_root: Path, config: dict, rules: dict) -> Dict[str, Path]:
    files: Dict[str, Path] = {}
    for relative in config["files"]:
        add_file(files, source_root, relative, rules)
    for directory in config["json_directories"]:
        base = source_root / directory
        if not base.is_dir():
            raise FileNotFoundError(f"directory dati prevista non trovata: {base}")
        for source in sorted(base.rglob("*.json")):
            rel = source.relative_to(source_root)
            if not excluded(rel, rules):
                files[PurePosixPath(rel).as_posix()] = source
    for directory in config.get("directories", []):
        base = source_root / directory
        if not base.is_dir():
            raise FileNotFoundError(f"directory asset prevista non trovata: {base}")
        for source in sorted(p for p in base.rglob("*") if p.is_file()):
            rel = source.relative_to(source_root)
            if not excluded(rel, rules):
                files[PurePosixPath(rel).as_posix()] = source
    return files


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def destination_files(root: Path, rules: dict) -> Dict[str, Path]:
    if not root.exists():
        return {}
    result: Dict[str, Path] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if not excluded(rel, rules):
            result[PurePosixPath(rel).as_posix()] = path
    return result


def compare(expected: Mapping[str, Path], destination: Path, rules: dict) -> ChangeSet:
    current = destination_files(destination, rules)
    expected_names = set(expected)
    current_names = set(current)
    added = sorted(expected_names - current_names)
    deleted = sorted(current_names - expected_names)
    updated = []
    unchanged = 0
    for name in sorted(expected_names & current_names):
        if digest(expected[name]) == digest(current[name]):
            unchanged += 1
        else:
            updated.append(name)
    return ChangeSet(tuple(added), tuple(updated), tuple(deleted), unchanged)


def git_info(source_root: Path) -> tuple[str, bool]:
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "-C", str(source_root), "status", "--porcelain"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True


def source_version(source_root: Path, version_file: str) -> str:
    root = ET.parse(source_root / version_file).getroot()
    return root.attrib.get("version", "unknown")


def print_changes(label: str, changes: ChangeSet, verbose: bool = False) -> None:
    print(
        f"{label}: +{len(changes.added)} ~{len(changes.updated)} "
        f"-{len(changes.deleted)} ={changes.unchanged}"
    )
    if verbose:
        for marker, names in (("+", changes.added), ("~", changes.updated), ("-", changes.deleted)):
            for name in names:
                print(f"  {marker} {name}")


def apply_changes(expected: Mapping[str, Path], destination: Path, changes: ChangeSet) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in changes.deleted:
        (destination / Path(name)).unlink()
    for name in (*changes.added, *changes.updated):
        target = destination / Path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(expected[name], target)
    for directory in sorted(
        (p for p in destination.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass


def write_state(path: Path, source_root: Path, manifest_path: Path, version: str, commit: str) -> None:
    state = {
        "schema_version": 1,
        "source": source_root.name,
        "source_version": version,
        "source_commit": commit,
        "manifest_sha256": digest(manifest_path),
        "synced_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    source_root = (
        args.source.resolve()
        if args.source
        else (APP_ROOT / manifest["source"]["default_relative_path"]).resolve()
    )
    if not source_root.is_dir():
        raise FileNotFoundError(f"sorgente motore non trovata: {source_root}")

    rules = manifest["exclude"]
    engine_cfg = manifest["engine"]
    assets_cfg = manifest["assets"]
    engine_destination = APP_ROOT / engine_cfg["destination"]
    assets_destination = APP_ROOT / assets_cfg["destination"]
    engine_files = collect_engine(source_root, engine_cfg, rules)
    asset_files = collect_assets(source_root, assets_cfg, rules)
    engine_changes = compare(engine_files, engine_destination, rules)
    asset_changes = compare(asset_files, assets_destination, rules)

    version = source_version(source_root, manifest["source"]["version_file"])
    commit, dirty = git_info(source_root)
    print(f"Sorgente: {source_root.name} v{version} @ {commit[:12]} ({'dirty' if dirty else 'clean'})")
    print_changes("Motore", engine_changes, args.verbose)
    print_changes("Asset", asset_changes, args.verbose)
    has_changes = engine_changes.has_changes or asset_changes.has_changes

    if args.apply:
        if dirty and not args.allow_dirty:
            print(
                "RIFIUTATO: la sorgente Git contiene modifiche non committate. "
                "Usare --allow-dirty solo dopo averle verificate.",
                file=sys.stderr,
            )
            return 2
        apply_changes(engine_files, engine_destination, engine_changes)
        apply_changes(asset_files, assets_destination, asset_changes)
        state_path = APP_ROOT / manifest["state_file"]
        write_state(state_path, source_root, manifest_path, version, commit)
        print(f"Sincronizzazione completata. Stato: {state_path.relative_to(APP_ROOT)}")
        return 0

    if args.check and has_changes:
        print("DIVERGENZA: eseguire --apply quando la sorgente è stata validata.", file=sys.stderr)
        return 1
    if not args.check:
        print("Anteprima soltanto: nessun file modificato. Usare --apply per applicare.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
        print(f"ERRORE: {exc}", file=sys.stderr)
        raise SystemExit(2)
