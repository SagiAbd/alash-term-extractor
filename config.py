"""
Central configuration for the alash-term-extractor pipeline.

Edit this file to change URLs, file paths, model names, and metadata
without touching the individual pipeline scripts.
"""

# ---------------------------------------------------------------------------
# 1_scrape.py — Selenium scraper
# ---------------------------------------------------------------------------
SCRAPER_DEFAULT_URL = "https://kazneb.kz/la/bookView/view?brId=1151021&simple=true"
SCRAPER_DEFAULT_OUTPUT_DIR = "output"
SCRAPER_PAGE_LOAD_TIMEOUT = 15   # seconds to wait for the viewer page to load
SCRAPER_IMAGE_CHANGE_TIMEOUT = 10  # seconds to wait for the image src to change
SCRAPER_MAX_RETRIES = 3          # download retry attempts per image

# ---------------------------------------------------------------------------
# 2_ocr.py — Gemini OCR
# ---------------------------------------------------------------------------
OCR_DEFAULT_INPUT_DIR = "output"
OCR_DEFAULT_OUTPUT_FILE = "ocr_results.json"
OCR_MODEL_NAME = "gemini-2.0-flash"

# ---------------------------------------------------------------------------
# 3_extract_terms.py — Term extraction
# ---------------------------------------------------------------------------
TERMS_INPUT_FILE = "ocr_results.json"
TERMS_OUTPUT_FILE = "terms.xlsx"
TERMS_OVERLAP_CHARS = 300        # characters from adjacent pages included as context
TERMS_MODEL_NAME = "gemini-2.5-flash"

# Metadata written into every extracted term row
CONST_YEAR = 2013
CONST_LINK = "https://kazneb.kz/la/bookView/view?brId=1151021&simple=true#"
CONST_AUTHOR = "Жұмабаев, Мағжан"
CONST_TITLE = "Шығармалары"
