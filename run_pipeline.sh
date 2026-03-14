#!/bin/bash
set -e

# Load environment variables from .env if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Install dependencies
pip install -q -r requirements.txt

# Usage examples:
#   ./run_pipeline.sh --url "https://kazneb.kz/kk/bookView/view?brId=1151021&simple=true"
#   TERMS_START=10 TERMS_END=50 ./run_pipeline.sh --url "..."
URL=""
TERMS_START="${TERMS_START:-}"
TERMS_END="${TERMS_END:-}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --url) URL="$2"; shift 2 ;;
        *) shift ;;
    esac
done

URL_ARG=""
if [ -n "$URL" ]; then
    URL_ARG="--url $URL"
fi

echo "=== Step 0: Scrape book metadata ==="
python3 0_metadata_scrape.py $URL_ARG

echo "=== Step 1: Scrape page images ==="
python3 1_scrape.py $URL_ARG

echo "=== Step 2: OCR images ==="
python3 2_ocr.py

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
