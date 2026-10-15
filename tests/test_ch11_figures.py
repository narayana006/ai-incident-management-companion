from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest


SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ch11_figures.py"
SPEC = importlib.util.spec_from_file_location("ch11_figures", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Chapter11FiguresTest(unittest.TestCase):
    def test_both_sources_are_accessible_print_safe_svg(self) -> None:
        records = [MODULE.validate_svg(MODULE.SOURCE_ROOT / name) for name in MODULE.FIGURE_NAMES]
        self.assertEqual(len(records), 2)
        self.assertEqual(len({record["title"] for record in records}), 2)
        self.assertTrue(all(len(record["description"]) >= 120 for record in records))

    def test_published_figures_match_sources_byte_for_byte(self) -> None:
        for name in MODULE.FIGURE_NAMES:
            self.assertEqual(
                (MODULE.SOURCE_ROOT / name).read_bytes(),
                (MODULE.BOOK_FIGURE_ROOT / name).read_bytes(),
            )

    def test_manifest_hashes_match_published_figures(self) -> None:
        manifest = json.loads(MODULE.MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["authority_effect"], "none")
        self.assertEqual(len(manifest["figures"]), 2)
        for record in manifest["figures"]:
            path = MODULE.BOOK_FIGURE_ROOT / record["file"]
            self.assertEqual(record["sha256"], MODULE.sha256_bytes(path.read_bytes()))
            self.assertEqual(
                record["published_path"],
                "generated/published-figures/" + record["file"],
            )

    def test_generation_is_deterministic_and_supports_external_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            figures = root / "book-figures"
            first = root / "first.json"
            second = root / "second.json"
            MODULE.generate(MODULE.SOURCE_ROOT, figures, first)
            MODULE.generate(MODULE.SOURCE_ROOT, figures, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            manifest = json.loads(first.read_text(encoding="utf-8"))
            committed = json.loads(MODULE.MANIFEST_PATH.read_text(encoding="utf-8"))
            for record, reference in zip(manifest["figures"], committed["figures"]):
                name = record["file"]
                # Published outside the companion, so the manifest says so.
                self.assertEqual(
                    record["published_path"], str((figures / name).resolve())
                )
                self.assertEqual(record["sha256"], reference["sha256"])
                self.assertEqual(
                    (figures / name).read_bytes(),
                    (MODULE.SOURCE_ROOT / name).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
