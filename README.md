# Alash Period Scientific Term Extractor

A pipeline for extracting scientific terminology from historical Kazakh books scanned on [kazneb.kz](https://kazneb.kz).  
It includes an optional metadata pre-step (`0_metadata_scrape.py`) plus the main 1→2→3 processing steps.

## Pipeline

```
0_metadata_scrape.py  →  updates config.py metadata fields
1_scrape.py  →  output/*.png
2_ocr.py     →  ocr_results.json
3_extract_terms.py  →  terms.xlsx
```

| Step | Script | What it does |
|------|--------|--------------|
| 0 (optional) | `0_metadata_scrape.py` | Uses Selenium + Gemini to extract book metadata (title/author/year/link/pages) and write it to `config.py` |
| 1 | `1_scrape.py` | Uses Selenium to download page images from the kazneb.kz book viewer |
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

### Run the full pipeline

```bash
bash run_pipeline.sh
```

### Run steps individually

```bash
# Step 0 (optional) — auto-fill metadata in config.py from book page
python 0_metadata_scrape.py --url "https://kazneb.kz/la/bookView/view?brId=1597551&simple=true"

# Step 1 — scrape all pages
python 1_scrape.py --url "https://kazneb.kz/la/bookView/view?brId=1597551&simple=true"

# Step 1 — scrape page range (inclusive)
python 1_scrape.py --start-page 26 --end-page 148

# Step 2 — OCR all images in input directory
python 2_ocr.py --input-dir output --output-file ocr_results.json

# Step 2 — OCR page range by filename page number (inclusive)
python 2_ocr.py --start-page 26 --end-page 29

# Step 3 — extract terms from all OCR records
python 3_extract_terms.py

# Step 3 — extract terms by page number range (inclusive)
python 3_extract_terms.py --start-page 26 --end-page 29

# Step 3 — index-based test run (0-based index in ocr_results.json)
python 3_extract_terms.py --start 5 --limit 10
```

## Safety Stops

To avoid accidental overwrite or mixing old/new runs:

- `1_scrape.py` stops if output folder is not empty.
- `2_ocr.py` stops if `ocr_results.json` (or selected `--output-file`) is non-empty.
- `3_extract_terms.py` stops if `terms.xlsx` already exists and is non-empty.

If you want to rerun, back up first, then clear or rename old outputs.

Example:

```bash
mv output output_backup_$(date +%Y%m%d_%H%M%S)
mv ocr_results.json ocr_results_backup_$(date +%Y%m%d_%H%M%S).json
mv terms.xlsx terms_backup_$(date +%Y%m%d_%H%M%S).xlsx
```

## Output

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
| Авторы / Жазылу жылы / Сілтеме | Metadata |

## Configuration

Main settings are in `config.py`:

```python
SCRAPER_DEFAULT_URL = "https://kazneb.kz/..."
OCR_DEFAULT_INPUT_DIR = "output"
TERMS_INPUT_FILE = "ocr_results.json"
TERMS_OUTPUT_FILE = "terms.xlsx"
TERMS_OVERLAP_CHARS = 300

CONST_TITLE = "..."
CONST_AUTHOR = "..."
CONST_YEAR = 1923
CONST_LINK = "https://kazneb.kz/..."
```

`0_metadata_scrape.py` can update `CONST_TITLE`, `CONST_AUTHOR`, `CONST_YEAR`, `CONST_LINK`, and `SCRAPER_DEFAULT_URL` automatically.
