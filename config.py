"""
Central configuration for the alash-term-extractor pipeline.

Edit this file to change URLs, file paths, model names, and metadata
without touching the individual pipeline scripts.
"""

# ---------------------------------------------------------------------------
# Pipeline output root
# All pipeline outputs live under:  OUTPUT_BASE_DIR/<book_dir_name>/
#   images       →  output/<book>/0001.png …
#   OCR JSON     →  output/<book>/ocr.json
#   Excel        →  output/<book>/terms.xlsx
#   resume state →  output/<book>/terms_state.json
# ---------------------------------------------------------------------------
OUTPUT_BASE_DIR = "output"

# ---------------------------------------------------------------------------
# 1_scrape.py — Selenium scraper
# ---------------------------------------------------------------------------
SCRAPER_DEFAULT_URL = "https://kazneb.kz/la/bookView/view?brId=1151021&simple=true"
SCRAPER_PAGE_LOAD_TIMEOUT = 15       # seconds to wait for the viewer page to load
SCRAPER_IMAGE_CHANGE_TIMEOUT = 10    # seconds to wait for the image src to change
SCRAPER_MAX_RETRIES = 3              # download retry attempts per image

# ---------------------------------------------------------------------------
# 2_ocr.py — Gemini OCR
# ---------------------------------------------------------------------------
OCR_MODEL_NAME = "gemini-2.0-flash"

# ---------------------------------------------------------------------------
# 3_extract_terms.py — Term extraction
# ---------------------------------------------------------------------------
TERMS_OVERLAP_CHARS = 300            # characters from adjacent pages included as context
TERMS_MODEL_NAME = "gemini-2.5-flash"

# Metadata written into every extracted term row
CONST_YEAR = 2013
CONST_LINK = "https://kazneb.kz/la/bookView/view?brId=1151021&simple=true#"
CONST_AUTHOR = "Жұмабаев, Мағжан"
CONST_TITLE = "Шығармалары"


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
