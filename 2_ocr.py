#!/usr/bin/env python3
"""
OCR script using Gemini API to preserve layout when extracting text from images.

Usage:
    python ocr.py --input-dir output --output-file ocr_results.json
    python ocr.py --api-key YOUR_API_KEY
"""

import argparse
import base64
import json
import logging
import time
import os
from pathlib import Path
from typing import List, Dict, Any

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DEFAULT_INPUT_DIR = "output"
DEFAULT_OUTPUT_FILE = "ocr_results.json"
MODEL_NAME = "gemini-2.0-flash"

def configure_genai(api_key: str | None = None):
    """Configure the Gemini API. Uses the provided key, or falls back to GEMINI_API_KEY env var."""
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("API key required: pass --api-key or set GEMINI_API_KEY in .env")
    genai.configure(api_key=key)


def get_sorted_images(input_dir: Path) -> List[Path]:
    """Return a sorted list of PNG image paths from the input directory."""
    if not input_dir.exists():
        log.error("Input directory not found: %s", input_dir)
        return []
    
    images = list(input_dir.glob("*.png"))
    # Sort by filename (assuming they are named like 0001.png, 0002.png)
    images.sort(key=lambda p: p.name)
    return images


def perform_ocr(image_path: Path, model) -> str:
    """Send image to Gemini API for OCR."""
    log.info("Processing %s...", image_path.name)
    
    try:
        # Load image data
        image_data = {
            "mime_type": "image/png",
            "data": image_path.read_bytes()
        }

        prompt = (
            "Transcribe the text in this image exactly as is. "
            "Preserve the layout, spacing, and line breaks to the best of your ability. "
            "Do not add any introductory or concluding remarks. "
            "If there are tables, try to preserve their structure."
        )

        response = model.generate_content(
            [prompt, image_data],
            safety_settings={
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
        )
        
        return response.text
    except Exception as e:
        log.error("Error processing %s: %s", image_path.name, e)
        # basic rate limit handling
        if "429" in str(e):
            log.warning("Rate limit hit, waiting 60s...")
            time.sleep(60)
            return perform_ocr(image_path, model) # Retry once
        return ""


def main():
    parser = argparse.ArgumentParser(description="OCR images using Gemini API")
    parser.add_argument(
        "--input-dir", "-i",
        default=DEFAULT_INPUT_DIR,
        type=Path,
        help=f"Directory containing images (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-file", "-o",
        default=DEFAULT_OUTPUT_FILE,
        type=Path,
        help=f"Output JSON file (default: {DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "--api-key", "-k",
        help="Gemini API Key (optional if GEMINI_API_KEY env var is set)",
    )
    
    args = parser.parse_args()
    
    try:
        configure_genai(args.api_key)
    except ValueError as e:
        log.error(e)
        return

    model = genai.GenerativeModel(MODEL_NAME)
    
    images = get_sorted_images(args.input_dir)
    if not images:
        log.warning("No images found in %s", args.input_dir)
        return

    results: List[Dict[str, Any]] = []
    
    # Check if output file exists and load existing results to resume if needed
    if args.output_file.exists():
        try:
            with open(args.output_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                if isinstance(existing_data, list):
                    # Filter out already processed images
                    processed_files = {item.get("file") for item in existing_data}
                    images = [img for img in images if img.name not in processed_files]
                    results = existing_data
                    log.info("Resuming from %d existing records...", len(results))
        except json.JSONDecodeError:
            log.warning("Output file exists but is not valid JSON. Starting fresh.")
    
    log.info("Found %d images to process", len(images))

    for i, img_path in enumerate(images):
        text = perform_ocr(img_path, model)
        
        # Try to extract page number from filename
        try:
            page_num = int(img_path.stem)
        except ValueError:
            page_num = -1

        result_entry = {
            "page": page_num,
            "file": img_path.name,
            "text": text
        }
        results.append(result_entry)
        
        # Save incrementally
        with open(args.output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
            
        # Respect rate limits (15 RPM for free tier, but safe side)
        time.sleep(4) 
    
    log.info("OCR complete. Results saved to %s", args.output_file)


if __name__ == "__main__":
    main()
