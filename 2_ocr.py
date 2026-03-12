#!/usr/bin/env python3
"""
OCR script using Gemini API to preserve layout when extracting text from images.

Usage:
    python ocr.py --input-dir output --output-file ocr_results.json
    python ocr.py --start-page 26 --end-page 29
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

from config import (
    OCR_DEFAULT_INPUT_DIR as DEFAULT_INPUT_DIR,
    OCR_DEFAULT_OUTPUT_FILE as DEFAULT_OUTPUT_FILE,
    OCR_MODEL_NAME as MODEL_NAME,
)

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)



def load_dotenv(env_path: Path = Path(".env")) -> None:
    """Load KEY=VALUE pairs from .env into process env without overwriting existing vars."""
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if (
                (value.startswith('"') and value.endswith('"'))
                or (value.startswith("'") and value.endswith("'"))
            ):
                value = value[1:-1]
            os.environ.setdefault(key, value)
    except OSError as exc:
        log.warning("Could not read %s: %s", env_path, exc)


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


def parse_page_num(image_path: Path) -> int:
    """Parse page number from image filename stem, return -1 if invalid."""
    try:
        return int(image_path.stem)
    except ValueError:
        return -1


def filter_images_by_page_range(
    images: List[Path], start_page: int | None, end_page: int | None
) -> List[Path]:
    """Filter images by inclusive page range based on filename page numbers."""
    if start_page is None and end_page is None:
        return images

    filtered: List[Path] = []
    invalid_name_count = 0
    for img in images:
        page_num = parse_page_num(img)
        if page_num < 0:
            invalid_name_count += 1
            continue
        if start_page is not None and page_num < start_page:
            continue
        if end_page is not None and page_num > end_page:
            continue
        filtered.append(img)

    if invalid_name_count:
        log.warning(
            "Skipped %d image(s) with non-numeric filenames while applying page range filter.",
            invalid_name_count,
        )
    return filtered


def output_file_has_content(output_file: Path) -> bool:
    """Return True if output JSON file exists and contains non-whitespace content."""
    if not output_file.exists():
        return False
    try:
        return bool(output_file.read_text(encoding="utf-8").strip())
    except OSError as exc:
        log.warning("Could not read %s: %s", output_file, exc)
        # Fail closed to avoid accidental overwrite of existing data.
        return True


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
    parser.add_argument(
        "--start-page", "-s",
        type=int,
        default=None,
        help="First page number to OCR (inclusive, based on filename stem)",
    )
    parser.add_argument(
        "--end-page", "-e",
        type=int,
        default=None,
        help="Last page number to OCR (inclusive, based on filename stem)",
    )
    
    args = parser.parse_args()
    load_dotenv()

    if args.start_page is not None and args.start_page < 1:
        parser.error("--start-page must be >= 1")
    if args.end_page is not None and args.end_page < 1:
        parser.error("--end-page must be >= 1")
    if (
        args.start_page is not None
        and args.end_page is not None
        and args.start_page > args.end_page
    ):
        parser.error("--start-page cannot be greater than --end-page")

    if output_file_has_content(args.output_file):
        log.error(
            "Output file is not empty: %s\n"
            "Stop to prevent overriding/mixing old files. Please back up or clear this file, then rerun.",
            args.output_file.resolve(),
        )
        return
    
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

    images = filter_images_by_page_range(images, args.start_page, args.end_page)
    if not images:
        if args.start_page is not None or args.end_page is not None:
            log.warning(
                "No images matched requested page range: %s-%s",
                args.start_page if args.start_page is not None else "*",
                args.end_page if args.end_page is not None else "*",
            )
        else:
            log.warning("No images available after filtering.")
        return

    results: List[Dict[str, Any]] = []
    
    if args.start_page is not None or args.end_page is not None:
        log.info(
            "Found %d images to process in page range %s-%s",
            len(images),
            args.start_page if args.start_page is not None else "*",
            args.end_page if args.end_page is not None else "*",
        )
    else:
        log.info("Found %d images to process", len(images))

    for i, img_path in enumerate(images):
        text = perform_ocr(img_path, model)
        
        page_num = parse_page_num(img_path)

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
