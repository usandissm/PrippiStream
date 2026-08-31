#!/usr/bin/env python3
"""Regression tests for queue de-duplication, offline gating and DB recovery."""

import importlib.util
import os
import sys
import tempfile
import threading
import time
import types


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYROOT = os.path.join(ROOT, "app", "src", "main", "python", "engine")


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PYROOT, relative))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


temp_dir = tempfile.TemporaryDirectory()
logger = types.ModuleType("platformcode.logger")
logger.info = lambda *args, **kwargs: None
logger.error = lambda *args, **kwargs: None
logger.debug = lambda *args, **kwargs: None
config = types.ModuleType("platformcode.config")
config.get_data_path = lambda: temp_dir.name
config.get_setting = lambda *args, **kwargs: ""

platformcode = types.ModuleType("platformcode")
platformcode.__path__ = []
platformcode.logger = logger
platformcode.config = config
sys.modules["platformcode"] = platformcode
sys.modules["platformcode.logger"] = logger
sys.modules["platformcode.config"] = config

downloads_db = load("platformcode.downloads_db", "platformcode/downloads_db.py")
platformcode.downloads_db = downloads_db
sys.modules["platformcode.downloads_db"] = downloads_db

hls = load("core.hls_downloader", "core/hls_downloader.py")
crypto = load("core.download_crypto", "core/download_crypto.py")
core = types.ModuleType("core")
core.__path__ = []
core.hls_downloader = hls
core.download_crypto = crypto
sys.modules["core"] = core
sys.modules["core.hls_downloader"] = hls
sys.modules["core.download_crypto"] = crypto

manager_module = load("platformcode.download_manager", "platformcode/download_manager.py")


class FakeItem:
    contentType = "episode"
    contentSerieName = "Test"
    contentSeason = 1
    thumbnail = ""
    fanart = ""
    channel = "streamingcommunity"
    url = "https://example.invalid/episode"

    def __init__(self, episode):
        self.contentEpisodeNumber = episode
        self.contentTitle = "Episode %d" % episode

    def tourl(self):
        return "fake://episode/%d" % self.contentEpisodeNumber


def wait_until(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_db_excludes_paused_and_repairs_completed():
    paused = {
        "key": "paused",
        "status": "paused",
        "progress": 20,
        "item_url": "fake://paused",
    }
    queued = {
        "key": "queued",
        "status": "queued",
        "progress": 10,
        "item_url": "fake://queued",
    }
    legacy_network = {
        "key": "legacy-network",
        "status": "error",
        "progress": 12,
        "item_url": "fake://legacy-network",
        "error": "<urlopen error [Errno 101] Network is unreachable>",
    }
    completed_path = os.path.join(temp_dir.name, "complete.ts")
    with open(completed_path, "wb") as handle:
        handle.write(b"valid offline content")
    downgraded = {
        "key": "complete",
        "status": "error",
        "progress": 100,
        "file_path": completed_path,
        "error": "network unavailable",
    }
    for entry in (paused, queued, legacy_network, downgraded):
        downloads_db.upsert(entry)

    assert [entry["key"] for entry in downloads_db.get_resumable()] == ["queued"]
    assert downloads_db.repair_completed() == 1
    assert downloads_db.migrate_legacy_network_errors() == 1
    assert {entry["key"] for entry in downloads_db.get_resumable()} == {
        "queued",
        "legacy-network",
    }
    assert downloads_db.get("complete")["status"] == "done"
    assert not downloads_db.update_fields_unless_done(
        "complete", status="error", error="stale worker"
    )
    assert downloads_db.get("complete")["status"] == "done"


def test_duplicate_is_ignored_without_changing_state():
    manager = manager_module.DownloadManager()
    manager_module._manager = manager
    manager._ensure_workers = lambda: None
    manager._ensure_poller = lambda: None
    manager_module._install_dns_cache = lambda: None

    item = FakeItem(10)
    assert manager.enqueue(item, 720)
    key = manager_module._entry_from_item(item)["key"]
    first_timestamp = downloads_db.get(key)["timestamp"]
    assert not manager.enqueue(item, 720)
    assert manager._q.qsize() == 1
    assert downloads_db.get(key)["status"] == "queued"
    assert downloads_db.get(key)["timestamp"] == first_timestamp


def test_offline_gate_blocks_following_jobs_until_validated():
    manager = manager_module.DownloadManager()
    manager_module._manager = manager
    manager_module._install_dns_cache = lambda: None
    manager._ensure_poller = lambda: None
    config.get_setting = lambda *args, **kwargs: "1"
    called = []

    def successful_job(job):
        called.append(job["key"])
        downloads_db.update_fields(job["key"], status="done", progress=100)

    manager._run_job = successful_job
    manager.set_network_available(False)
    first = FakeItem(21)
    second = FakeItem(22)
    manager.enqueue(first, 0)
    manager.enqueue(second, 0)
    key1 = manager_module._entry_from_item(first)["key"]
    key2 = manager_module._entry_from_item(second)["key"]

    assert wait_until(lambda: downloads_db.get(key1)["status"] == "waiting_network")
    assert called == []
    assert downloads_db.get(key2)["status"] == "queued"

    manager.set_network_available(True)
    assert wait_until(lambda: downloads_db.get(key2)["status"] == "done")
    assert called == [key1, key2]


if __name__ == "__main__":
    test_db_excludes_paused_and_repairs_completed()
    test_duplicate_is_ignored_without_changing_state()
    test_offline_gate_blocks_following_jobs_until_validated()
    print("download state regression tests: OK")
