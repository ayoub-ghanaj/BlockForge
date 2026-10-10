"""Release boundaries: source agreement, reproducibility, and private-file exclusion."""

import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.package_addon import PACKAGE_FILES, build_package
from tools.release_metadata import release_version

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def checkout(self, directory):
        root = Path(directory)
        shutil.copytree(ROOT / "minecraft_builder", root / "minecraft_builder")
        shutil.copytree(ROOT / "docs/releases", root / "docs/releases")
        shutil.copy2(ROOT / "LICENSE", root / "LICENSE")
        return root

    def test_build_excludes_private_files_and_ignores_checkout_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.checkout(directory)
            source = root / "minecraft_builder"
            for name in (".env", "credentials.json", "scene.blend", "resource-pack.zip"):
                (source / name).write_text("private local test input")
            first = build_package(root)
            archive_path = root / "dist" / first["file"]
            first_bytes = archive_path.read_bytes()
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                self.assertTrue(PACKAGE_FILES <= names)
                self.assertTrue(
                    all(name in PACKAGE_FILES or name.endswith(".py") for name in names)
                )
                self.assertIsNone(archive.testzip())
            for path in source.rglob("*"):
                if path.is_file():
                    os.utime(path, (1_000_000_000, 1_000_000_000))
            self.assertEqual(build_package(root), first)
            self.assertEqual(archive_path.read_bytes(), first_bytes)

    def test_mismatched_versions_tags_and_missing_notices_fail_before_packaging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.checkout(directory)
            with self.assertRaisesRegex(ValueError, "Tag must be"):
                release_version(root, "v0.0.0")
            manifest = root / "minecraft_builder/blender_manifest.toml"
            original = manifest.read_text()
            manifest.write_text(
                original.replace(f'version = "{release_version(root)}"', 'version = "0.0.0"')
            )
            with self.assertRaisesRegex(ValueError, "differs from bl_info"):
                build_package(root)
            self.assertFalse((root / "dist").exists())
            manifest.write_text(original)
            (root / "minecraft_builder/THIRD_PARTY_NOTICES.txt").unlink()
            with self.assertRaisesRegex(ValueError, "Package files missing"):
                build_package(root)
            self.assertFalse((root / "dist").exists())


if __name__ == "__main__":
    unittest.main()
