from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch06_figures.py"
SPEC = importlib.util.spec_from_file_location("ch06_figures", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Chapter6FiguresTest(unittest.TestCase):
    def test_all_five_sources_are_accessible_svg(self) -> None:
        records = [MODULE.validate_svg(MODULE.SOURCE_ROOT / name) for name in MODULE.FIGURE_NAMES]
        self.assertEqual(len(records), 5)
        self.assertEqual(len({record["title"] for record in records}), 5)

    def test_published_files_match_sources_byte_for_byte(self) -> None:
        for name in MODULE.FIGURE_NAMES:
            self.assertEqual(
                (MODULE.SOURCE_ROOT / name).read_bytes(),
                (MODULE.BOOK_FIGURE_ROOT / name).read_bytes(),
            )

    def test_manifest_hashes_match_published_files(self) -> None:
        manifest = json.loads(MODULE.MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["figures"]), 5)
        for record in manifest["figures"]:
            path = MODULE.BOOK_FIGURE_ROOT / record["file"]
            self.assertEqual(record["sha256"], MODULE.sha256_bytes(path.read_bytes()))
            self.assertEqual(
                record["published_path"],
                "generated/published-figures/" + record["file"],
            )

    def test_manifest_names_the_root_the_run_actually_published_to(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            figures = root / "figures"
            manifest_path = root / "manifest.json"
            MODULE.generate(MODULE.SOURCE_ROOT, figures, manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            committed = json.loads(MODULE.MANIFEST_PATH.read_text(encoding="utf-8"))
            for record, reference in zip(manifest["figures"], committed["figures"]):
                name = record["file"]
                self.assertEqual(
                    record["published_path"], str((figures / name).resolve())
                )
                self.assertEqual(record["sha256"], reference["sha256"])
                self.assertEqual(
                    (figures / name).read_bytes(), (MODULE.SOURCE_ROOT / name).read_bytes()
                )

    def test_generation_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            figures = root / "figures"
            first = root / "first.json"
            second = root / "second.json"
            MODULE.generate(MODULE.SOURCE_ROOT, figures, first)
            MODULE.generate(MODULE.SOURCE_ROOT, figures, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
