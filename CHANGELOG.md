# Changelog

All notable updates in this repository.

## 2026-03-12 (2)

### Added

- Structured output layout: all pipeline artifacts for a book now live under `output/<author>__<title>/`.
  - Images → `output/<book>/images/`
  - OCR JSON → `output/<book>/ocr.json`
  - Excel → `output/<book>/terms.xlsx`
  - Resume state → `output/<book>/terms_state.json`
- `config.py`: added `OUTPUT_BASE_DIR` and `book_dir_name()` helper that builds the folder name from `CONST_AUTHOR` + `CONST_TITLE` (set by `0_metadata_scrape.py`).
- `3_extract_terms.py`: incremental save — xlsx and state JSON are written after every LLM call; re-running the script resumes from the last processed page automatically (no manual page tracking needed).
- `run_pipeline.sh`: added step 0 (`0_metadata_scrape.py`) and `TERMS_START` / `TERMS_END` env-var support for passing `--start-page` / `--end-page` to step 3.

### Changed

- Removed separate `ocr/` and `terms/` top-level directories in favour of the single `output/<book>/` subfolder structure.
- Removed the fail-fast "output file not empty" guard from `3_extract_terms.py`; replaced by resume logic that skips already-processed pages.
- `config.py`: replaced `SCRAPER_DEFAULT_OUTPUT_DIR`, `OCR_DEFAULT_INPUT_DIR`, `OCR_DEFAULT_OUTPUT_FILE`, `TERMS_INPUT_FILE`, `TERMS_OUTPUT_FILE` with a single `OUTPUT_BASE_DIR`.

## 2026-03-12

### Added

- Documented optional metadata pre-step `0_metadata_scrape.py` in README.
- Added page-range OCR support in `2_ocr.py` via `--start-page` and `--end-page`.
- Added page-range extraction support in `3_extract_terms.py` via `--start-page` and `--end-page`.
- Kept backward-compatible index mode in `3_extract_terms.py` via `--start` and `--limit`.
- Added automatic `.env` loading in `2_ocr.py` and `3_extract_terms.py`.

### Changed

- Updated extraction prompt in `3_extract_terms.py` to explicitly include pedagogical and Kazakh-language terms.
- Updated extraction prompt to treat bolded terms as candidate terms for extraction.
- Updated documentation (`README.md`) with new range options and safety-stop behavior.

### Fixed

- Fixed `1_scrape.py` navigation flow for ranged scraping by using direct viewer navigation (prevents `.../bookView/undefined` errors).
- Added fail-fast protection in `1_scrape.py`: stop when output image directory is not empty.
- Added fail-fast protection in `2_ocr.py`: stop when OCR output JSON is non-empty.
- Added fail-fast protection in `3_extract_terms.py`: stop when output Excel file is non-empty.
