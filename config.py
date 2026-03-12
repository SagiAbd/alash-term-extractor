"""
Central configuration for the alash-term-extractor pipeline.

Book-specific metadata (author, title, year, link) is loaded at runtime from
.metadata.json, which is written by 0_metadata_scrape.py and is gitignored.
All other settings can be edited here directly.
"""

import json as _json
from pathlib import Path as _Path

# ---------------------------------------------------------------------------
# Load metadata written by 0_metadata_scrape.py
# ---------------------------------------------------------------------------
_METADATA_FILE = _Path(__file__).parent / ".metadata.json"
_meta: dict = {}
if _METADATA_FILE.exists():
    try:
        _meta = _json.loads(_METADATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Pipeline output root
# All pipeline outputs live under:  OUTPUT_BASE_DIR/<book_dir_name>/
#   images       →  output/<book>/images/0001.png …
#   OCR JSON     →  output/<book>/ocr.json
#   Excel        →  output/<book>/terms.xlsx
#   resume state →  output/<book>/terms_state.json
# ---------------------------------------------------------------------------
OUTPUT_BASE_DIR = "output"

# ---------------------------------------------------------------------------
# 1_scrape.py — Selenium scraper
# ---------------------------------------------------------------------------
SCRAPER_DEFAULT_URL = _meta.get("link") or "https://kazneb.kz/la/bookView/view?brId=1151021&simple=true"
SCRAPER_PAGE_LOAD_TIMEOUT = 15       # seconds to wait for the viewer page to load
SCRAPER_IMAGE_CHANGE_TIMEOUT = 10    # seconds to wait for the image src to change
SCRAPER_MAX_RETRIES = 3              # download retry attempts per image

# ---------------------------------------------------------------------------
# 2_ocr.py — Gemini OCR
# ---------------------------------------------------------------------------
OCR_MODEL_NAME = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# 3_extract_terms.py — Term extraction
# ---------------------------------------------------------------------------
TERMS_OVERLAP_CHARS = 300            # characters from adjacent pages included as context
TERMS_MODEL_NAME = "gemini-2.5-flash"
TERMS_FALLBACK_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash"]
PARALLEL_REQUESTS = 50             # concurrent API requests (OCR and term extraction)

# Metadata written into every extracted term row (sourced from .metadata.json)
CONST_YEAR   = _meta.get("year")   or 2013
CONST_LINK   = (_meta.get("link")  or "https://kazneb.kz/la/bookView/view?brId=1151021&simple=true").rstrip("#") + "#"
CONST_AUTHOR = _meta.get("author") or "Жұмабаев, Мағжан"
CONST_TITLE  = _meta.get("title")  or "Шығармалары"


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def book_dir_name() -> str:
    """
    Build a filesystem-safe directory/file name from CONST_AUTHOR and CONST_TITLE.
    Run 0_metadata_scrape.py first so these are populated.
    Example: "Жұмабаев_Мағжан__Шығармалары"
    """
    import re

    def sanitize(s: str) -> str:
        s = re.sub(r'[/\\:*?"<>|]', '', s)          # strip forbidden chars
        s = re.sub(r'[\s,;]+', '_', s.strip())       # spaces/commas → underscores
        return s.strip('_')

    author = sanitize(CONST_AUTHOR) if CONST_AUTHOR else ""
    title  = sanitize(CONST_TITLE)  if CONST_TITLE  else ""

    if author and title:
        return f"{author}__{title}"
    return author or title or "unknown"


def book_id_from_url(url: str) -> str:
    """Extract the brId query parameter from a kazneb.kz viewer URL."""
    from urllib.parse import urlparse, parse_qs
    try:
        qs = parse_qs(urlparse(url).query)
        br_ids = qs.get("brId", [])
        if br_ids:
            return br_ids[0]
    except Exception:
        pass
    return "unknown"
