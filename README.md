# Alash Period Scientific Term Extractor

A pipeline for extracting scientific terminology from historical Kazakh books scanned on [kazneb.kz](https://kazneb.kz).
It includes an optional metadata pre-step (`0_metadata_scrape.py`) plus the main 1→2→3 processing steps.

## Pipeline

```
0_metadata_scrape.py   →  .metadata.json (title, author, year, link, total_pages)
1_scrape_parallel.py   →  output/<author>__<title>/images/*.png  (20 workers)
2_ocr.py               →  output/<author>__<title>/ocr.json
3_extract_terms.py     →  output/<author>__<title>/terms.xlsx
```

All outputs for a book are grouped under one subfolder of `output/`, named after the author and title set by step 0.

| Step | Script | What it does |
|------|--------|--------------|
| 0 | `0_metadata_scrape.py` | Uses Selenium + Gemini to extract book metadata (title/author/year/link/pages) and write it to `.metadata.json` |
| 1 | `1_scrape_parallel.py` | Splits pages into 20 chunks and runs 20 instances of `1_scrape.py` simultaneously |
| 2 | `2_ocr.py` | Sends each image to Gemini Vision API and transcribes the text |
| 3 | `3_extract_terms.py` | Sends OCR text to Gemini and extracts Alash-era scientific terms into Excel |

## Setup

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# edit .env and add your Gemini API key
```

`2_ocr.py` and `3_extract_terms.py` auto-load `.env` from the project root.

## Usage

### Run the full pipeline for a book

```bash
# Step 0 — extract metadata from the book page (run this first)
python3 0_metadata_scrape.py --url "https://kazneb.kz/kk/bookView/view?brId=XXXXXX&simple=true"

# Step 1 — scrape all pages in parallel (20 workers by default)
python3 1_scrape_parallel.py

# Step 2 — OCR all images
python3 2_ocr.py

# Step 3 — extract terms into Excel
python3 3_extract_terms.py
```

### Step 1 options

```bash
# Change number of parallel workers
python3 1_scrape_parallel.py --workers 10

# Scrape a specific page range
python3 1_scrape_parallel.py --start-page 1 --end-page 100

# Override URL (if different from what step 0 saved)
python3 1_scrape_parallel.py --url "https://kazneb.kz/kk/bookView/view?brId=XXXXXX&simple=true"
```

### Step 2 & 3 options

```bash
# OCR a specific page range
python3 2_ocr.py --start-page 26 --end-page 29

# Extract terms for a page range
python3 3_extract_terms.py --start-page 26 --end-page 29

# Extract terms for specific pages
python3 3_extract_terms.py --pages 12,47,83

# Re-process pages that failed in the last run (reads failed_term_pages from .metadata.json)
python3 3_extract_terms.py --rerun-failed

# Index-based test run (0-based index in ocr.json)
python3 3_extract_terms.py --start 5 --limit 10
```

## Safety Stops & Resume

- `1_scrape.py` stops if the images folder is not empty (prevents mixing runs).
- `2_ocr.py` stops if `ocr.json` already exists and is non-empty.
- `3_extract_terms.py` **resumes automatically** — it loads `terms_state.json` and skips pages already processed. You can stop it at any time with Ctrl-C and rerun to continue from where you left off.
- `3_extract_terms.py` records pages where all Gemini models failed in `.metadata.json` under `failed_term_pages`. Run `--rerun-failed` to retry them; successfully recovered pages are removed from the list automatically.

To start a book from scratch, remove or rename its output folder:

```bash
mv "output/Жұмабаев_Мағжан__Шығармалары" "output/Жұмабаев_Мағжан__Шығармалары_backup"
```

## Output

All files for a book are written to `output/<author>__<title>/`:

| File | Description |
|------|-------------|
| `images/0001.png` … | Scraped page images |
| `ocr.json` | OCR transcriptions per page |
| `terms.xlsx` | Extracted terms (deduplicated, with metadata header) |
| `terms_state.json` | Resume state — tracks which pages are already processed |

`terms.xlsx` contains one row per term with the following columns:

| Column | Description |
|--------|-------------|
| Алаш термині | Term exactly as written in the source |
| Заманауи термин | Modern Kazakh equivalent |
| Сала / Кіші сала | Field / Subfield |
| Алаш түсініктемесі | Author's original definition (verbatim) |
| Анықтама бар ма | Whether original text explicitly defines the term |
| Заманауи түсініктеме | Modern scientific definition |
| Контекст | Surrounding sentences from the source |
| Авторы / Жазылу жылы / Сілтеме | Metadata from `config.py` |

## Configuration

Main settings are in `config.py`:

```python
OUTPUT_BASE_DIR = "output"          # all outputs go here

SCRAPER_DEFAULT_URL = "https://kazneb.kz/..."
TERMS_OVERLAP_CHARS = 300

# Written into every term row and into the Excel metadata header.
# Populated automatically by 0_metadata_scrape.py:
CONST_TITLE  = "..."
CONST_AUTHOR = "..."
CONST_YEAR   = 1923
CONST_LINK   = "https://kazneb.kz/..."
```

`0_metadata_scrape.py` updates `CONST_TITLE`, `CONST_AUTHOR`, `CONST_YEAR`, `CONST_LINK`, and `SCRAPER_DEFAULT_URL` automatically. The output subfolder name is derived from `CONST_AUTHOR` and `CONST_TITLE` at runtime.
