#!/usr/bin/env python3
"""Build one Pages artifact, with the resume derived from the current index.html."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path


STATIC_FILES = (
    "index.html", "style.css", "script.js", "resume.css", "photo.jpg",
    "favicon.svg", "onest-cyrillic.woff2", "onest-latin.woff2", "OFL.txt",
    "pavel-gorodnichiy.vcf", ".nojekyll",
)
PDF_NAME = "pavel-gorodnichiy-resume.pdf"


def build(source_dir: Path, output_dir: Path) -> None:
    source_dir, output_dir = source_dir.resolve(), output_dir.resolve()
    if source_dir == output_dir or output_dir in source_dir.parents:
        raise ValueError("The build output must be separate from the source files")
    output_dir.mkdir(parents=True, exist_ok=True)
    allowed = set(STATIC_FILES) | {PDF_NAME, "resume.html"}
    if any(path.name not in allowed or path.is_symlink() or not path.is_file()
           for path in output_dir.iterdir()):
        raise ValueError("Output contains unexpected files; choose a new empty output directory")
    for name in STATIC_FILES:
        shutil.copyfile(source_dir / name, output_dir / name)
    subprocess.run(
        [sys.executable, str(source_dir / "build_resume.py"),
         "--source", str(source_dir / "index.html"), "--output-dir", str(output_dir)],
        check=True,
    )
    pdf = (output_dir / PDF_NAME).read_bytes()
    if not pdf.startswith(b"%PDF-"):
        raise ValueError("The resume build did not produce a PDF")
    version = hashlib.sha256(pdf).hexdigest()[:16]
    # Every published HTML revision points browsers to the matching PDF version.
    pattern = re.compile(r'(?P<start>href=[\"\'])' + re.escape(PDF_NAME)
                         + r'(?:\?[^\"\']*)?(?P<end>[\"\'])')
    for name in ("index.html", "resume.html"):
        path = output_dir / name
        text, count = pattern.subn(
            lambda match: match["start"] + PDF_NAME + "?v=" + version + match["end"],
            path.read_text(encoding="utf-8"),
        )
        if not count:
            raise ValueError(f"No PDF download link in {name}")
        path.write_text(text, encoding="utf-8")
    print(f"Built site and resume ({len(pdf):,} bytes, version {version})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path, default=Path("_site"))
    args = parser.parse_args()
    build(args.source_dir, args.output_dir)
