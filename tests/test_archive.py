from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ingestion.archive import (
    archive_root_generated_artifacts,
    check_project_hygiene,
    find_root_generated_artifacts,
)


class ArchiveRootArtifactsTests(unittest.TestCase):
    def test_finds_root_leftovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "ho_definities_curated.json"
            artifact.write_text("{}", encoding="utf-8")

            self.assertEqual([artifact], find_root_generated_artifacts(root))
            self.assertTrue(check_project_hygiene(root))

    def test_does_not_move_active_data_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_file = root / "data" / "ho_definities_curated.json"
            data_file.parent.mkdir()
            data_file.write_text("{}", encoding="utf-8")

            result = archive_root_generated_artifacts(root)

            self.assertTrue(data_file.exists())
            self.assertEqual([], result["moved"])

    def test_dry_run_does_not_move(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "ho_definities_index.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")

            result = archive_root_generated_artifacts(root, dry_run=True)

            self.assertTrue(artifact.exists())
            self.assertTrue(result["dry_run"])
            self.assertEqual("ho_definities_index.jsonl", result["moved"][0]["from"])
            self.assertIn("data/archive/root_leftovers_", result["moved"][0]["to"])

    def test_real_archive_moves_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "chunks.jsonl"
            artifact.write_text("{}\n", encoding="utf-8")

            result = archive_root_generated_artifacts(root)
            destination = root / result["moved"][0]["to"]

            self.assertFalse(artifact.exists())
            self.assertTrue(destination.exists())
            self.assertIn("data/archive/root_leftovers_", destination.as_posix())

    def test_existing_archive_filename_collision_uses_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "last_build_report.md"
            artifact.write_text("new", encoding="utf-8")
            archive_dir = root / "data" / "archive" / "root_leftovers_2026-06-18_1456"
            archive_dir.mkdir(parents=True)
            existing = archive_dir / "last_build_report.md"
            existing.write_text("old", encoding="utf-8")

            with patch("src.ingestion.archive._timestamp", return_value="2026-06-18_1456"):
                result = archive_root_generated_artifacts(root)

            destination = root / result["moved"][0]["to"]
            self.assertTrue(existing.exists())
            self.assertEqual("old", existing.read_text(encoding="utf-8"))
            self.assertTrue(destination.exists())
            self.assertNotEqual(existing, destination)


if __name__ == "__main__":
    unittest.main()
