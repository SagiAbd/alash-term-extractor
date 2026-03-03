#!/bin/bash
set -e

# Load environment variables from .env if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Install dependencies
pip install -q -r requirements.txt

echo "=== Step 1: Scrape page images ==="
python 1_scrape.py "$@"

echo "=== Step 2: OCR images ==="
python 2_ocr.py

echo "=== Step 3: Extract terms ==="
python 3_extract_terms.py

echo "Done! Output: terms.xlsx"
