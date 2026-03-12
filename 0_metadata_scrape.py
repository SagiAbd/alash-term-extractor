#!/usr/bin/env python3
"""
0_metadata_scrape.py — Book metadata extractor for kazneb.kz

Loads the book viewer page with Selenium, captures its HTML and a screenshot,
then asks Gemini to carefully extract:
  - Book title
  - Author(s)
  - Publication year
  - Canonical book URL / link
  - Total number of pages

The extracted values are written back into the relevant fields of config.py so
the rest of the pipeline (1_scrape → 2_ocr → 3_extract_terms) automatically
picks them up without any manual editing.

Usage:
    python3 0_metadata_scrape.py
    python3 0_metadata_scrape.py --url "https://kazneb.kz/la/bookView/view?brId=XXXXX&simple=true"
    python3 0_metadata_scrape.py --api-key YOUR_KEY --no-headless
"""

import argparse
import base64
import json
import logging
import os
import re
import time
from pathlib import Path

import google.generativeai as genai
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from config import SCRAPER_DEFAULT_URL, SCRAPER_PAGE_LOAD_TIMEOUT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

METADATA_MODEL = "gemini-2.0-flash"

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
METADATA_PROMPT = """\
You are a careful bibliographic metadata extractor.

You will receive:
1. The full HTML source of a digital book viewer page from kazneb.kz.
2. A screenshot of the same page (use it as a visual cross-check).

Your task is to extract the following fields with HIGH precision. \
Accuracy matters — this data will be stored in the project configuration \
and used in every term exported from the book.

FIELDS TO EXTRACT:
1. title       — Full title of the book exactly as it appears on the page \
(in the original language, usually Kazakh or Russian). Do NOT translate. \
Strip leading/trailing whitespace. \
IMPORTANT: if the book is part of a series or multi-volume set, include the \
volume designation as printed — e.g. "Шығармалары. 1-том", "Алты томдық \
шығармалар жинағы. 2-том", "Собрание сочинений. Том 3". \
Look for volume markers in these forms: "N-том", "Том N", "N том", \
"Т. N", "Кітап N", "Volume N", "Part N", "Бөлім N" — if any appear \
near the title (on the cover, title page, or header), append them to the \
title string separated by ". ".
2. author      — Full name(s) of the author(s) as printed. If multiple \
authors, join with "; ". If no author is found return an empty string "".
3. year        — Publication year as a 4-digit integer (e.g. 2013). \
Look for it in these places (in priority order): \
(a) A bibliographic/imprint citation line such as \
"Мектеп, 2013. — 504 б." or "Алматы: Мектеп, 2013" — extract the 4-digit year. \
(b) Kazakh publishing imprint lines that start with "Теруге" or "Басуга", e.g. \
"Теруге 15. 06. 2017 ж. берілді." or "Басуга 13. 07. 2017 ж. қол қойылды." — \
these always contain the publication year; extract the 4-digit number ending in " ж.". \
Note: digits in these dates may be separated by spaces ("15. 06. 2017") or not. \
(c) Any other date string in DD.MM.YYYY, D. MM. YYYY, or YYYY-MM-DD format \
(e.g. "29.05.2013") — extract the 4-digit year portion. \
(d) A standalone year written in the page metadata or copyright block. \
If none of these are found or the year is ambiguous, return null.
4. total_pages — Total number of pages in the book as an integer. \
Look for a "last page" navigation button that calls onNavigate(N), \
or any visible page-count text. Return null if not found.
5. link        — The canonical URL of this book page. \
Prefer a clean permalink (e.g. the href of a "share" or "permalink" element). \
If none, reconstruct it from the brId query parameter visible in the page URL \
in the form: https://kazneb.kz/la/bookView/view?brId=<ID>&simple=true

STRICT RULES:
- Return ONLY a valid JSON object, nothing else — no markdown, no explanation.
- Do not invent or guess values. If a field cannot be reliably determined, \
use null (for integers) or "" (for strings).
- For the "year" field, only return a year that is explicitly printed on the \
page (copyright line, title page scan caption, publication metadata block, etc.). \
Do NOT infer the year from context.
- For "total_pages", prefer the numeric argument in onNavigate(N) on the \
last-page button "ffbtn" over any other source.

OUTPUT FORMAT (JSON only):
{
  "title": "...",
  "author": "...",
  "year": 1923,
  "total_pages": 409,
  "link": "https://kazneb.kz/la/bookView/view?brId=1597551&simple=true"
}
"""

# ---------------------------------------------------------------------------
# Selenium helper
# ---------------------------------------------------------------------------

def create_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(30)
    return driver


def fetch_page_snapshot(driver: webdriver.Chrome) -> tuple[str, bytes]:
    """Capture HTML source and screenshot from the currently loaded viewer page."""
    time.sleep(2)  # let JS settle
    page_source = driver.page_source
    screenshot = driver.get_screenshot_as_png()
    log.info("Snapshot taken. HTML length: %d chars", len(page_source))
    return page_source, screenshot


def navigate_back_one_page(driver: webdriver.Chrome) -> bool:
    """Click the previous-page button. Returns True on success."""
    try:
        prev_btn = driver.find_element(By.CSS_SELECTOR, "a.pbtn")
        prev_btn.click()
        time.sleep(2)  # wait for the page image to change
        return True
    except Exception as e:
        log.warning("Could not click previous-page button: %s", e)
        return False


def open_viewer(url: str, headless: bool) -> webdriver.Chrome:
    """Open the Chrome driver and load the book viewer URL."""
    driver = create_driver(headless=headless)
    log.info("Loading viewer: %s", url)
    driver.get(url)
    WebDriverWait(driver, SCRAPER_PAGE_LOAD_TIMEOUT).until(
        EC.presence_of_element_located((By.ID, "img"))
    )
    time.sleep(3)  # let JS finish rendering navigation elements
    return driver

# ---------------------------------------------------------------------------
# Gemini extraction
# ---------------------------------------------------------------------------

def load_dotenv(env_path: Path = Path(".env")) -> None:
    """Load KEY=VALUE pairs from .env into process env without overwriting existing vars."""
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


def extract_metadata_with_ai(page_source: str, screenshot_png: bytes) -> dict:
    """Send HTML + screenshot to Gemini and parse the returned JSON."""
    model = genai.GenerativeModel(METADATA_MODEL)

    screenshot_b64 = base64.b64encode(screenshot_png).decode()
    image_part = {"mime_type": "image/png", "data": screenshot_b64}

    # Trim HTML if it's very large to stay within token limits
    html_snippet = page_source[:60_000]

    prompt_parts = [
        METADATA_PROMPT,
        f"\n\n--- HTML SOURCE (first 60 000 chars) ---\n{html_snippet}\n--- END HTML ---",
        image_part,
    ]

    log.info("Sending data to Gemini (%s) for metadata extraction...", METADATA_MODEL)
    response = model.generate_content(
        prompt_parts,
        generation_config={"response_mime_type": "application/json"},
    )

    raw = response.text.strip()
    log.info("Raw Gemini response: %s", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to fish out JSON from surrounding text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse JSON from Gemini response: {raw}")

# ---------------------------------------------------------------------------
# config.py writer
# ---------------------------------------------------------------------------

METADATA_JSON_PATH = Path(__file__).parent / ".metadata.json"


def write_metadata_to_json(metadata: dict):
    author = metadata.get("author") or ""
    year = metadata.get("year")
    link = (metadata.get("link") or "").rstrip("#")
    title = metadata.get("title") or ""
    total_pages = metadata.get("total_pages")

    payload = {
        "author":      author,
        "title":       title,
        "year":        year,
        "link":        link,
        "total_pages": total_pages,
    }
    METADATA_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
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

REQUIRED_FIELDS = ("title", "author", "year", "total_pages")  # fields we must all have


def _metadata_complete(metadata: dict) -> bool:
    """Return True only if all required fields are present and non-null/non-empty."""
    for field in REQUIRED_FIELDS:
        val = metadata.get(field)
        if val is None or val == "":
            return False
    return True


def _merge_metadata(base: dict, update: dict) -> dict:
    """Fill in missing fields in *base* from *update*."""
    merged = dict(base)
    for field in REQUIRED_FIELDS:
        if merged.get(field) is None or merged.get(field) == "":
            new_val = update.get(field)
            if new_val is not None and new_val != "":
                log.info("  Filled missing field '%s' = %s", field, new_val)
                merged[field] = new_val
    # link / title are always taken from the first successful response
    if not merged.get("link"):
        merged["link"] = update.get("link", "")
    if not merged.get("title"):
        merged["title"] = update.get("title", "")
    return merged


def scrape_with_retry(
    url: str, headless: bool, max_back_pages: int = 7
) -> dict:
    """
    Open the viewer at *url*, grab metadata from Gemini, and — if any required
    field is still missing — step back one page and try again, up to
    *max_back_pages* times.
    """
    driver = open_viewer(url, headless)
    try:
        page_source, screenshot = fetch_page_snapshot(driver)
        metadata = extract_metadata_with_ai(page_source, screenshot)

        for attempt in range(1, max_back_pages + 1):
            if _metadata_complete(metadata):
                log.info("All required metadata fields found after %d attempt(s).", attempt)
                break

            missing = [f for f in REQUIRED_FIELDS
                       if metadata.get(f) is None or metadata.get(f) == ""]
            log.info(
                "Attempt %d/%d: missing fields %s — stepping back one page.",
                attempt, max_back_pages, missing,
            )

            ok = navigate_back_one_page(driver)
            if not ok:
                log.warning("Cannot go further back — stopping retry.")
                break

            page_source, screenshot = fetch_page_snapshot(driver)
            new_metadata = extract_metadata_with_ai(page_source, screenshot)
            metadata = _merge_metadata(metadata, new_metadata)
        else:
            missing = [f for f in REQUIRED_FIELDS
                       if metadata.get(f) is None or metadata.get(f) == ""]
            if missing:
                log.warning(
                    "Exhausted %d back-page retries. Still missing: %s",
                    max_back_pages, missing,
                )

        return metadata
    finally:
        driver.quit()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape book metadata from kazneb.kz and store it in config.py"
    )
    parser.add_argument(
        "--url",
        default=SCRAPER_DEFAULT_URL,
        help="Book viewer URL (default: from config.py)",
    )
    parser.add_argument(
        "--api-key", "-k",
        default=None,
        help="Gemini API key (optional if GEMINI_API_KEY env var is set)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Show the browser window (useful for debugging)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print extracted metadata but do NOT write to config.py",
    )
    args = parser.parse_args()
    load_dotenv()

    try:
        configure_genai(args.api_key)
    except ValueError as e:
        log.error(e)
        return

    metadata = scrape_with_retry(
        url=args.url,
        headless=not args.no_headless,
        max_back_pages=7,
    )

    if args.dry_run:
        log.info("Dry-run mode — not writing to .metadata.json")
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return

    write_metadata_to_json(metadata)


if __name__ == "__main__":
    main()

