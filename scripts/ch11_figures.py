#!/usr/bin/env python3
"""Validate and publish the two static Chapter 11 planning figures."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import os
from pathlib import Path


COMPANION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = COMPANION_ROOT.parent
SOURCE_ROOT = COMPANION_ROOT / "diagrams" / "src"
BOOK_FIGURE_ROOT = Path(os.environ.get("BOOK_FIGURE_ROOT", COMPANION_ROOT / "generated" / "published-figures"))
MANIFEST_PATH = COMPANION_ROOT / "generated" / "ch11_figure_manifest.json"
FIGURE_NAMES = [
    "figure-11-1-gated-adoption-roadmap.svg",
    "figure-11-2-ninety-day-starter-plan.svg",
]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def published_label(path: Path) -> str:
    """Report where the figure was actually written.

    Inside the companion the path is relative to the companion root; a figure
    published into a manuscript tree or any other external root is reported
    absolute, so the manifest cannot name a location this run did not write.
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(COMPANION_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def validate_svg(path: Path) -> dict[str, str | int]:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    opening = re.search(r"<svg\b[^>]*>", text)
    if opening is None or 'xmlns="http://www.w3.org/2000/svg"' not in opening.group(0):
        raise ValueError(f"{path.name} root must be SVG")
    if 'role="img"' not in opening.group(0) or 'aria-labelledby="title desc"' not in opening.group(0):
        raise ValueError(f"{path.name} requires role=img and aria-labelledby='title desc'")
    title_match = re.search(r'<title\s+id="title">(.*?)</title>', text, re.DOTALL)
    desc_match = re.search(r'<desc\s+id="desc">(.*?)</desc>', text, re.DOTALL)
    title = (title_match.group(1) if title_match else "").strip()
    desc = (desc_match.group(1) if desc_match else "").strip()
    if not title:
        raise ValueError(f"{path.name} requires a non-empty title")
    if len(desc) < 120:
        raise ValueError(f"{path.name} requires a useful long description")
    if "<foreignObject" in text:
        raise ValueError(f"{path.name} must not contain foreignObject")
    if "mermaid" in text.lower():
        raise ValueError(f"{path.name} must not contain Mermaid source")
    if "%" in text:
        raise ValueError(f"{path.name} must not display an aggregate percentage")
    forbidden = ["maturity score", "autonomy tier", "automatic promotion"]
    for phrase in forbidden:
        if phrase in text.lower():
            raise ValueError(f"{path.name} contains prohibited phrase {phrase!r}")
    if not re.search(r'viewBox="0 0 1200 (?:900|920)"', opening.group(0)):
        raise ValueError(f"{path.name} must use the print-safe Chapter 11 viewBox")
    return {
        "file": path.name,
        "sha256": sha256_bytes(raw),
        "bytes": len(raw),
        "title": title,
        "description": desc,
    }


def generate(
    source_root: Path = SOURCE_ROOT,
    book_root: Path = BOOK_FIGURE_ROOT,
    manifest_path: Path = MANIFEST_PATH,
) -> None:
    records = []
    book_root.mkdir(parents=True, exist_ok=True)
    for name in FIGURE_NAMES:
        source = source_root / name
        if not source.is_file():
            raise ValueError(f"missing figure source {source}")
        record = validate_svg(source)
        target = book_root / name
        shutil.copyfile(source, target)
        if target.read_bytes() != source.read_bytes():
            raise RuntimeError(f"published figure drift for {name}")
        record["published_path"] = published_label(target)
        records.append(record)
        print(f"published {target.resolve()}")
    manifest = {
        "manifest_version": "ch11-static-figures-1",
        "artifact_class": "illustrative_template",
        "source_format": "accessible_svg",
        "authority_effect": "none",
        "figures": records,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {manifest_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--book-root", type=Path, default=BOOK_FIGURE_ROOT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()
    generate(args.source_root, args.book_root, args.manifest)


if __name__ == "__main__":
    main()
