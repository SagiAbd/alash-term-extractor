#!/usr/bin/env python3
"""
1_scrape_adebiportal.py — PDF page image extractor for adebiportal.kz

Downloads the PDF from an adebiportal.kz viewer URL and converts each page
to a PNG image, matching the output format of 1_scrape.py (kazneb).

Output: output/<book>/images/0001.png, 0002.png, ...
Also saves the original PDF as: output/<book>/book.pdf

Usage:
    python3 1_scrape_adebiportal.py --url "https://adebiportal.kz/web/viewer.php?file=...&ln=kz"
    python3 1_scrape_adebiportal.py --url "..." --start-page 1 --end-page 100
"""

import argparse
import json
import logging
import os
import shutil
import time
from pathlib import Path

import fitz  # PyMuPDF
import requests

from config import (
    OUTPUT_BASE_DIR,
    book_dir_name,
    pdf_url_from_adebiportal,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

METADATA_FILE = Path(__file__).parent / ".metadata.json"
RENDER_DPI = 200  # higher DPI for OCR quality


def get_total_pages_from_metadata() -> int | None:
    if METADATA_FILE.exists():
        try:
            data = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
            return data.get("total_pages")
        except Exception:
            pass
    return None


def download_pdf(url: str, dest: Path) -> Path:
    """Download a PDF from the given URL."""
    log.info("Downloading PDF from %s", url)
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    size_mb = dest.stat().st_size / (1024 * 1024)
    log.info("PDF saved to %s (%.1f MB)", dest, size_mb)
    return dest


def convert_pdf_to_images(
    pdf_path: Path,
    output_dir: Path,
    start_page: int = 1,
    end_page: int | None = None,
    dpi: int = RENDER_DPI,
):
    """Convert PDF pages to PNG images in the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    total = len(doc)

    if end_page is None or end_page > total:
        end_page = total
    if start_page < 1:
        start_page = 1

    log.info("Converting pages %d–%d of %d to PNG (DPI=%d)", start_page, end_page, total, dpi)

    mat = fitz.Matrix(dpi / 72, dpi / 72)
    existing = {int(f.stem) for f in output_dir.glob("*.png") if f.stem.isdigit()}
    skipped = 0

    for page_num in range(start_page, end_page + 1):
        file_name = f"{page_num:04d}.png"
        save_path = output_dir / file_name

        if page_num in existing:
            skipped += 1
            continue

        page = doc[page_num - 1]  # 0-indexed
        pix = page.get_pixmap(matrix=mat)
        pix.save(str(save_path))

    doc.close()

    if skipped:
        log.info("Skipped %d already-existing pages", skipped)
    converted = len(list(output_dir.glob("*.png")))
    log.info("Done. %d/%d page images in %s", converted, end_page - start_page + 1, output_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Download adebiportal.kz PDF and convert pages to images"
    )
    parser.add_argument("--url", required=True, help="adebiportal.kz viewer URL")
    parser.add_argument("--output-dir", "-o", default=None, help="Output directory for images")
    parser.add_argument("--start-page", "-s", type=int, default=1, help="First page (default: 1)")
    parser.add_argument("--end-page", "-e", type=int, default=None, help="Last page (default: all)")
    args = parser.parse_args()

    # Resolve paths
    book_base = Path(OUTPUT_BASE_DIR) / book_dir_name()
    output_dir = Path(args.output_dir) if args.output_dir else book_base / "images"
    pdf_dest = book_base / "book.pdf"

    # Download PDF (skip if already present)
    if pdf_dest.exists():
        log.info("PDF already exists at %s, skipping download", pdf_dest)
    else:
        pdf_url = pdf_url_from_adebiportal(args.url)
        if not pdf_url:
            log.error("Could not extract PDF URL from: %s", args.url)
            return
        download_pdf(pdf_url, pdf_dest)

    # Convert to images
    convert_pdf_to_images(
        pdf_path=pdf_dest,
        output_dir=output_dir,
        start_page=args.start_page,
        end_page=args.end_page,
    )


if __name__ == "__main__":
    _t0 = time.time()
    main()
    _elapsed = time.time() - _t0
    log.info("Total time: %dm %02ds", int(_elapsed // 60), int(_elapsed % 60))
    if os.environ.get("PLAY_SOUND", "").lower() in ("1", "true", "yes"):
        _snd = Path(__file__).parent / "done.mp3"
        if _snd.exists():
            os.system(f'afplay -t 10 "{_snd}"')
