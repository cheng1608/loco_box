"""Configuration updates keep per-song settings and survive write failures."""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.core import config


class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name, value in (("DATA_DIR", root), ("SETTINGS_FILE", root / "settings.json")):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.store = config.ConfigStore()

    def test_parallel_updates_preserve_each_others_fields(self):
        self.store.set("music", {"tracks": [1, 3], "mode": "single"})
        barrier = threading.Barrier(9)

        def update(index):
            barrier.wait()
            self.store.update("music", {"field_%s" % index: index})

        workers = [threading.Thread(target=update, args=(i,)) for i in range(8)]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
        saved = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved["features"]["music"], self.store.get("music"))
        self.assertEqual(saved["features"]["music"]["tracks"], [1, 3])
        self.assertEqual(len(saved["features"]["music"]), 10)

    def test_failed_replace_keeps_old_file_and_memory(self):
        self.store.set("music", {"mode": "single"})
        original = config.SETTINGS_FILE.read_bytes()
        with patch.object(config.os, "replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.store.update("music", {"mode": "shuffle"})
        self.assertEqual(config.SETTINGS_FILE.read_bytes(), original)
        self.assertEqual(self.store.get("music"), {"mode": "single"})
        self.assertEqual(list(config.DATA_DIR.glob("*.tmp")), [])

    def test_returned_settings_do_not_mutate_store(self):
        values = {"tracks": [1, 2]}
        self.store.set("music", values)
        values["tracks"].clear()
        loaded = self.store.get("music")
        loaded["tracks"].append(3)
        self.assertEqual(self.store.get("music"), {"tracks": [1, 2]})

    def test_flat_settings_migrate_without_losing_global_values(self):
        config.SETTINGS_FILE.write_text(json.dumps({
            "delay": "2", "com_port": "COM6", "custom": {"keep": True},
        }), encoding="utf-8-sig")
        store = config.ConfigStore()
        self.assertEqual(store.get("box_monitor"), {"delay": "2"})
        self.assertEqual(store.get_global("com_port"), "COM6")
        self.assertEqual(store.get_global("custom"), {"keep": True})
        saved = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("delay", saved)
        self.assertEqual(config.ConfigStore().get("box_monitor"), {"delay": "2"})

    def test_mixed_settings_keep_current_values_and_remove_old_fields(self):
        config.SETTINGS_FILE.write_text(json.dumps({
            "delay": "1", "brightness": "200",
            "features": {"box_monitor": {"delay": "3"}, "music": {"mode": "shuffle"}},
        }), encoding="utf-8")
        store = config.ConfigStore()
        self.assertEqual(store.get("box_monitor"), {"delay": "3", "brightness": "200"})
        self.assertEqual(store.get("music"), {"mode": "shuffle"})
        saved = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("delay", saved)
        self.assertNotIn("brightness", saved)

    def test_failed_migration_keeps_original_settings(self):
        original = b'{"delay": "2"}'
        config.SETTINGS_FILE.write_bytes(original)
        with patch.object(config.os, "replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                config.ConfigStore()
        self.assertEqual(config.SETTINGS_FILE.read_bytes(), original)
        self.assertEqual(list(config.DATA_DIR.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
