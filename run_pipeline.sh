#!/bin/bash
set -e

# Load environment variables from .env if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Install dependencies
pip install -q -r requirements.txt

# Optional page range for term extraction (passed as env vars or args)
# Usage examples:
#   ./run_pipeline.sh                          # full pipeline, all pages
#   TERMS_START=10 TERMS_END=50 ./run_pipeline.sh
TERMS_START="${TERMS_START:-}"
TERMS_END="${TERMS_END:-}"

echo "=== Step 0: Scrape book metadata ==="
python 0_metadata_scrape.py

echo "=== Step 1: Scrape page images ==="
python 1_scrape.py "$@"

echo "=== Step 2: OCR images ==="
python 2_ocr.py

echo "=== Step 3: Extract terms ==="
TERMS_ARGS=""
if [ -n "$TERMS_START" ]; then
    TERMS_ARGS="$TERMS_ARGS --start-page $TERMS_START"
fi
if [ -n "$TERMS_END" ]; then
    TERMS_ARGS="$TERMS_ARGS --end-page $TERMS_END"
fi
python 3_extract_terms.py $TERMS_ARGS

echo "Done! Output saved to output/<author>__<title>/"
