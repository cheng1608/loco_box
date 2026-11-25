"""Resource rejection and directory-swap failures must preserve the old set."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.import_pet_resources import find_resources, import_resources


class PetResourceImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source" / "_internal" / "assets"
        self.source.mkdir(parents=True)
        (self.source / "all.pb").write_bytes(b"candidate-descriptor")
        (self.source / "gamedata.json").write_text("{}", encoding="utf-8")
        self.target = self.root / "pet_viewer" / "resources"
        self.target.mkdir(parents=True)
        (self.target / "all.pb").write_bytes(b"existing-descriptor")
        (self.target / "gamedata.json").write_text('{"existing": true}', encoding="utf-8")
        self.history = self.target.parent / "history.sqlite3"
        self.history.write_bytes(b"encounters")

    def test_rejected_resource_set_does_not_touch_existing_files_or_history(self):
        with self.assertRaisesRegex(ValueError, "配置"):
            import_resources(self.source, self.target)
        self.assertEqual((self.target / "all.pb").read_bytes(), b"existing-descriptor")
        self.assertEqual(json.loads((self.target / "gamedata.json").read_text()), {"existing": True})
        self.assertEqual(self.history.read_bytes(), b"encounters")
        self.assertEqual(sorted(path.name for path in self.target.parent.iterdir()), ["history.sqlite3", "resources"])

    def test_failed_swap_restores_complete_previous_set(self):
        import os

        replace = os.replace

        def fail_new_set(source, destination):
            if Path(source).name.startswith(".resources.staging-"):
                raise OSError("simulated sharing violation")
            return replace(source, destination)

        with patch("scripts.import_pet_resources._validate"), \
                patch("scripts.import_pet_resources.os.replace", side_effect=fail_new_set):
            with self.assertRaisesRegex(OSError, "sharing violation"):
                import_resources(self.source, self.target)
        self.assertEqual((self.target / "all.pb").read_bytes(), b"existing-descriptor")
        self.assertEqual(self.history.read_bytes(), b"encounters")
        self.assertFalse(list(self.target.parent.glob("resources.backup-*")))

    def test_successful_swap_preserves_old_set_and_records_hashes(self):
        with patch("scripts.import_pet_resources._validate") as validate:
            result = import_resources(self.root / "source", self.target, "test-resource")
        validate.assert_called_once()
        self.assertEqual((self.target / "all.pb").read_bytes(), b"candidate-descriptor")
        self.assertEqual((Path(result["backup"]) / "all.pb").read_bytes(), b"existing-descriptor")
        manifest = json.loads((self.target / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "test-resource")
        self.assertEqual(manifest["files"]["all.pb"]["bytes"], 20)
        self.assertEqual(len(manifest["files"]["all.pb"]["sha256"]), 64)
        self.assertEqual(self.history.read_bytes(), b"encounters")

    def test_ambiguous_installation_requires_explicit_resource_directory(self):
        second = self.root / "source" / "other"
        second.mkdir()
        (second / "all.pb").write_bytes(b"other-descriptor")
        (second / "gamedata.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "多套资源"):
            find_resources(self.root / "source")


if __name__ == "__main__":
    unittest.main()
