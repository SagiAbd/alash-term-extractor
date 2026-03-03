# Alash Period Scientific Term Extractor

A three-step pipeline for extracting scientific terminology from historical Kazakh books scanned on [kazneb.kz](https://kazneb.kz).

## Pipeline

```
1_scrape.py  →  output/*.png
2_ocr.py     →  ocr_results.json
3_extract_terms.py  →  terms.xlsx
```

| Step | Script | What it does |
|------|--------|--------------|
| 1 | `1_scrape.py` | Uses Selenium to download page images from the kazneb.kz book viewer |
| 2 | `2_ocr.py` | Sends each image to Gemini Vision API and transcribes the text |
| 3 | `3_extract_terms.py` | Sends OCR text to Gemini and extracts Alash-era scientific terms into Excel |

## Setup

```bash
pip install -r requirements.txt

cp .env.example .env
# edit .env and add your Gemini API key
```

## Usage

### Run the full pipeline

```bash
bash run_pipeline.sh
```

### Run steps individually

```bash
# Step 1 — scrape all pages of a book
python 1_scrape.py --url "https://kazneb.kz/la/bookView/view?brId=1597551&simple=true"

# Step 2 — OCR the downloaded images
python 2_ocr.py --input-dir output --output-file ocr_results.json

# Step 3 — extract terms (add --limit N for a test run)
python 3_extract_terms.py
python 3_extract_terms.py --start 5 --limit 10
```

## Output

`terms.xlsx` contains one row per term with the following columns:

| Column | Description |
|--------|-------------|
| Алаш термині | Term exactly as written in the source |
| Заманауи термин | Modern Kazakh equivalent |
| Сала / Кіші сала | Field / Subfield |
| Алаш түсініктемесі | Author's original definition (verbatim) |
| Заманауи түсініктеме | Modern scientific definition |
| Контекст | Surrounding sentences from the source |
| Авторы / Жазылу жылы / Сілтеме | Metadata |

## Configuration

Book metadata is set via constants at the top of `3_extract_terms.py`:

```python
CONST_AUTHOR = "Е.Омарұлы - Физика"
CONST_YEAR   = 1923
CONST_LINK   = "https://kazneb.kz/..."
OVERLAP_CHARS = 300  # context characters borrowed from adjacent pages
```
