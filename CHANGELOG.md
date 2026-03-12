# Changelog

All notable updates in this repository.

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
