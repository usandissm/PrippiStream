#!/usr/bin/env python3
"""Contract test for the bounded low-power Home archive pipeline."""

import pathlib
import sys
import threading
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
PYTHON_ROOT = ROOT / "app" / "src" / "main" / "python"
sys.path.insert(0, str(PYTHON_ROOT))

import bridge  # noqa: E402


class LowPowerHomePipelineTest(unittest.TestCase):
    def test_archive_fetch_is_serial_and_bounded(self):
        bridge.init()
        from platformcode import prippihome

        original_get_data = prippihome._get_data
        original_build_item = prippihome._build_item
        calls = []
        active = 0
        maximum_active = 0
        lock = threading.Lock()

        def fake_get_data(url):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
                calls.append(url)
            time.sleep(0.01)
            with lock:
                active -= 1
            return {"props": {"titles": {"data": [{"id": len(calls)}]}}}

        try:
            prippihome._get_data = fake_get_data
            prippihome._build_item = lambda raw, host: object()
            rows = prippihome._fetch_archive_rows(
                "https://example.invalid",
                {},
                0,
                max_workers=1,
                max_new_rows=3,
            )
        finally:
            prippihome._get_data = original_get_data
            prippihome._build_item = original_build_item

        self.assertEqual(3, len(calls))
        self.assertEqual(3, len(rows))
        self.assertEqual(1, maximum_active)


if __name__ == "__main__":
    unittest.main()
