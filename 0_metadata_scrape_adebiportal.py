#!/usr/bin/env python3
"""
0_metadata_scrape_adebiportal.py — Book metadata extractor for adebiportal.kz

Downloads the PDF from an adebiportal.kz viewer URL, renders the first few
pages with PyMuPDF, and asks Gemini to extract bibliographic metadata.

The extracted values are written to .metadata.json so the rest of the pipeline
(1_scrape_adebiportal → 2_ocr → 3_extract_terms) picks them up automatically.

Usage:
    python3 0_metadata_scrape_adebiportal.py --url "https://adebiportal.kz/web/viewer.php?file=...&ln=kz"
    python3 0_metadata_scrape_adebiportal.py --url "..." --dry-run
"""

import argparse
import base64
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path

import fitz  # PyMuPDF
import google.generativeai as genai
import requests

from config import pdf_url_from_adebiportal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

METADATA_MODEL = "gemini-2.5-flash"
METADATA_JSON_PATH = Path(__file__).parent / ".metadata.json"
RENDER_DPI = 150  # resolution for rendering PDF pages to images
MAX_PREVIEW_PAGES = 5  # how many pages to send to Gemini

METADATA_PROMPT = """\
You are a careful bibliographic metadata extractor.

You will receive rendered images of the first few pages of a digitised book
from the adebiportal.kz digital library.

Your task is to extract the following fields with HIGH precision.

FIELDS TO EXTRACT:
1. title       — Full title of the book exactly as it appears (in the original
   language, usually Kazakh or Russian). Do NOT translate. Strip leading/trailing
   whitespace. If multi-volume, include the volume designation
   (e.g. "Шығармалары. 1-том").
2. author      — Full name(s) of the author(s) as printed. Join multiple
   authors with "; ". Return "" if no author is found.
3. year        — Publication year as a 4-digit integer.
   Look for it in bibliographic lines like "Алматы: Мектеп, 2013",
   copyright lines, or Kazakh imprint lines starting with "Теруге" / "Басуга".
   Return null if not found.
4. total_pages — Will be filled automatically from the PDF. Return null.

STRICT RULES:
- Return ONLY a valid JSON object, nothing else.
- Do not invent or guess values.
- For "year", only return a year explicitly printed on the page.

OUTPUT FORMAT (JSON only):
{
  "title": "...",
  "author": "...",
  "year": 1923,
  "total_pages": null
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_dotenv(env_path: Path = Path(".env")) -> None:
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if (
                (value.startswith('"') and value.endswith('"'))
                or (value.startswith("'") and value.endswith("'"))
            ):
                value = value[1:-1]
            os.environ.setdefault(key, value)
    except OSError as exc:
        log.warning("Could not read %s: %s", env_path, exc)


def configure_genai(api_key: str | None = None):
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("API key required: pass --api-key or set GEMINI_API_KEY in .env")
    genai.configure(api_key=key)


def download_pdf(url: str, dest: Path) -> Path:
    """Download a PDF from the given URL. Returns the path to the saved file."""
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


def render_pages_as_png(pdf_path: Path, page_indices: list[int], dpi: int = RENDER_DPI) -> list[bytes]:
    """Render specific PDF pages as PNG byte arrays."""
    doc = fitz.open(pdf_path)
    images = []
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    for idx in page_indices:
        if idx >= len(doc):
            break
        page = doc[idx]
        pix = page.get_pixmap(matrix=mat)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def get_total_pages(pdf_path: Path) -> int:
    doc = fitz.open(pdf_path)
    total = len(doc)
    doc.close()
    return total


def extract_metadata_with_ai(page_images: list[bytes]) -> dict:
    """Send rendered page images to Gemini and parse the returned JSON."""
    model = genai.GenerativeModel(METADATA_MODEL)

    prompt_parts = [METADATA_PROMPT]
    for i, img_bytes in enumerate(page_images):
        prompt_parts.append(f"\n--- Page {i + 1} ---")
        prompt_parts.append({
            "mime_type": "image/png",
            "data": base64.b64encode(img_bytes).decode(),
        })

    log.info("Sending %d page image(s) to Gemini (%s) for metadata extraction...",
             len(page_images), METADATA_MODEL)
    response = model.generate_content(
        prompt_parts,
        generation_config={"response_mime_type": "application/json"},
    )

    raw = response.text.strip()
    log.info("Raw Gemini response: %s", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse JSON from Gemini response: {raw}")


def write_metadata_to_json(metadata: dict):
    author = metadata.get("author") or ""
    year = metadata.get("year")
    link = metadata.get("link") or ""
    title = metadata.get("title") or ""
    total_pages = metadata.get("total_pages")

    payload = {
        "author": author,
        "title": title,
        "year": year,
        "link": link,
        "total_pages": total_pages,
    }
    METADATA_JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("Metadata written to %s", METADATA_JSON_PATH)
    log.info("─── Extracted metadata ───────────────────────────")
    log.info("  Title       : %s", title or "(not found)")
    log.info("  Author      : %s", author or "(not found)")
    log.info("  Year        : %s", year if year is not None else "(not found)")
    log.info("  Total pages : %s", total_pages if total_pages is not None else "(not found)")
    log.info("  Link        : %s", link or "(not found)")
    log.info("──────────────────────────────────────────────────")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape book metadata from an adebiportal.kz PDF and store it in .metadata.json"
    )
    parser.add_argument("--url", required=True, help="adebiportal.kz viewer URL")
    parser.add_argument("--api-key", "-k", default=None, help="Gemini API key")
    parser.add_argument("--dry-run", action="store_true", help="Print metadata but do NOT write")
    args = parser.parse_args()

    load_dotenv()
    configure_genai(args.api_key)

    # Resolve direct PDF URL
    pdf_url = pdf_url_from_adebiportal(args.url)
    if not pdf_url:
        log.error("Could not extract PDF URL from: %s", args.url)
        return

    # Download PDF to a temp file
    tmp_dir = Path(tempfile.mkdtemp(prefix="adebiportal_"))
    pdf_path = tmp_dir / "book.pdf"
    download_pdf(pdf_url, pdf_path)

    # Get total pages
    total_pages = get_total_pages(pdf_path)
    log.info("PDF has %d pages", total_pages)

    # Render first N pages for metadata extraction
    preview_count = min(MAX_PREVIEW_PAGES, total_pages)
    page_images = render_pages_as_png(pdf_path, list(range(preview_count)))
    log.info("Rendered %d preview pages", len(page_images))

    # Extract metadata via Gemini
    metadata = extract_metadata_with_ai(page_images)
    metadata["total_pages"] = total_pages
    metadata["link"] = args.url

    if args.dry_run:
        log.info("Dry-run mode — not writing to .metadata.json")
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return

    write_metadata_to_json(metadata)

    # Clean up temp file
    pdf_path.unlink(missing_ok=True)
    tmp_dir.rmdir()


if __name__ == "__main__":
    _t0 = time.time()
    main()
    _elapsed = time.time() - _t0
    log.info("Total time: %dm %02ds", int(_elapsed // 60), int(_elapsed % 60))
