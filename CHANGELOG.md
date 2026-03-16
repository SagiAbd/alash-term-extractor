# Changelog

All notable updates in this repository.

## 2026-03-16 (3)

### Fixed

- `3_extract_terms.py`: strip illegal control characters (`\x00–\x08`, `\x0b`, `\x0c`, `\x0e–\x1f`) from cell values before writing to xlsx — prevents `IllegalCharacterError` crash when extracted text contains LaTeX or other embedded control characters.

## 2026-03-16 (2)

### Changed

- `run_batch.py`: `.list.json` now accepts objects with optional `start_page` and `end_page` fields alongside plain URL strings; if set, the values are passed as `--start-page` / `--end-page` to `3_extract_terms.py`. Plain strings and omitted fields default to the full page range.

## 2026-03-16

### Changed

- `1_scrape.py`: removed fail-fast non-empty directory guard; replaced with resume logic — already-downloaded pages are detected and skipped automatically.
- `1_scrape_parallel.py`: added crash recovery — leftover `_tmp_scrape/` files from a previous interrupted run are merged into the output directory on startup; already-downloaded pages are detected and excluded from the new run; workers now write directly to the final output directory (temp dirs removed); exits immediately if all pages are already present.

## 2026-03-15

### Added

- `3_extract_terms.py`: `--pages 1,5,10` flag to process specific page numbers directly.
- `3_extract_terms.py`: `--rerun-failed` flag — reads `failed_term_pages` from `.metadata.json` and re-processes those pages; pages that succeed are removed from the list, pages that still fail remain.
- `3_extract_terms.py`: failed pages (all models exhausted) are now tracked and written to `.metadata.json` under `failed_term_pages` after each run.
- `run_batch.py`: new batch pipeline runner — reads URLs from `.list.json`, runs the full pipeline (0 → 1 → 2 → 3 → rerun-failed) for each book sequentially. Deduplicates output folders by appending `_1`, `_2`, etc. when a folder already exists. Plays `done.mp3` once at the very end.
- `PLAY_SOUND` env var: all individual scripts now check `PLAY_SOUND` (default: `false`). Set `PLAY_SOUND=true` to enable sound on individual script runs. `run_batch.py` always plays sound at the end regardless.

### Changed

- Sound in `0_metadata_scrape.py`, `1_scrape_parallel.py`, `2_ocr.py`, `3_extract_terms.py` is now gated behind `PLAY_SOUND` env var (default off).

## 2026-03-14

### Added

- `1_scrape_parallel.py`: new wrapper that splits the page range into N equal chunks and runs N instances of `1_scrape.py` simultaneously, each writing to an isolated temp directory; merges all images into the final `output/<book>/images/` folder on completion. Default workers: 20.
- Added total elapsed time log line at the end of `0_metadata_scrape.py`, `1_scrape_parallel.py`, `2_ocr.py`, and `3_extract_terms.py`.

### Changed

- Updated README pipeline diagram and usage section to reflect new flow: `0_metadata_scrape.py` → `1_scrape_parallel.py` → `2_ocr.py` → `3_extract_terms.py`.
- `0_metadata_scrape.py`, `2_ocr.py`, `config.py`: upgraded fallback/default Gemini model references from `gemini-2.0-flash` → `gemini-2.5-flash`.

## 2026-03-13

### Changed

- `3_extract_terms.py`: removed `subfield` and `significance` output fields to reduce token usage.
- `3_extract_terms.py`: context field reduced to 1 sentence in description.
- `config.py`: `TERMS_OVERLAP_CHARS` reduced from 300 → 150 to halve adjacent-page context tokens.

## 2026-03-12 (4)

### Changed

- `3_extract_terms.py`: rewrote extraction prompt — goal now explicitly framed as proving early 20th-century Kazakh scientific vocabulary; criteria tightened to scientific/professional lexicon; "if in doubt, skip" rule; common words and administrative terms excluded by example; terms normalised to base form (case suffixes stripped); terms kept as short as possible.
- `3_extract_terms.py`: `is_definition` now requires an explicit explanatory sentence ("X — бұл Y"); mere usage no longer qualifies.
- `3_extract_terms.py`: added fallback model chain (`gemini-2.0-flash` → `gemini-1.5-flash`) — blocked responses immediately try the next model instead of failing.
- `config.py`: added `TERMS_FALLBACK_MODELS` list.

### Fixed

- `3_extract_terms.py`: `response.text` access now wrapped in `ValueError` catch so blocked API responses no longer crash the process.

### Added

- `3_extract_terms.py`: deduplication by `Алаш термині` (case-insensitive) runs after every page; duplicate count reported in final summary log line.

## 2026-03-12 (3)

### Changed

- `0_metadata_scrape.py`: writes extracted metadata to `.metadata.json` (gitignored) instead of patching `config.py` source — removes fragile regex rewriting.
- `config.py`: loads `.metadata.json` at import time; hardcoded values serve as fallbacks when the file is absent.
- `0_metadata_scrape.py`: improved title-extraction prompt to include volume designations ("1-том", "Том 3", "Кітап N", etc.) appended to the title string.
- `.gitignore`: added `.metadata.json`.

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
