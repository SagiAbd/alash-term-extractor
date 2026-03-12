#!/usr/bin/env python3
"""
OCR script using Gemini API to preserve layout when extracting text from images.

Usage:
    python ocr.py --input-dir output --output-file ocr_results.json
    python ocr.py --start-page 26 --end-page 29
    python ocr.py --api-key YOUR_API_KEY
"""

import argparse
import json
import logging
import time
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any

from config import (
    OUTPUT_BASE_DIR,
    OCR_MODEL_NAME as MODEL_NAME,
    PARALLEL_REQUESTS,
    book_dir_name,
)

OCR_FALLBACK_MODEL_NAME = "gemini-2.0-flash"

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


def load_existing_results(output_file: Path) -> List[Dict[str, Any]]:
    """Load existing OCR results from output file, return empty list if none."""
    if not output_file.exists():
        return []
    try:
        content = output_file.read_text(encoding="utf-8").strip()
        if not content:
            return []
        return json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read existing results from %s: %s", output_file, exc)
        return []


SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

PROMPT = (
    "Transcribe the text in this image exactly as is. "
    "Preserve the layout, spacing, and line breaks to the best of your ability. "
    "Do not add any introductory or concluding remarks. "
    "If there are tables, try to preserve their structure."
)


def _call_model(image_path: Path, model) -> str:
    """Call model once and return text. Raises on any error."""
    image_data = {"mime_type": "image/png", "data": image_path.read_bytes()}
    response = model.generate_content([PROMPT, image_data], safety_settings=SAFETY_SETTINGS)
    return response.text


def perform_ocr(image_path: Path, primary_model, fallback_model) -> str:
    """Send image to Gemini API for OCR with retries and fallback model."""
    log.info("Processing %s...", image_path.name)

    def try_with_model(model, model_name: str, attempts: int) -> str | None:
        for attempt in range(1, attempts + 1):
            try:
                return _call_model(image_path, model)
            except Exception as e:
                err = str(e)
                log.error(
                    "Error processing %s with %s (attempt %d/%d): %s",
                    image_path.name, model_name, attempt, attempts, e,
                )
                if attempt < attempts:
                    if "429" in err:
                        wait = 60 * attempt
                        log.warning("Rate limit hit, waiting %ds...", wait)
                        time.sleep(wait)
                    else:
                        time.sleep(5)
        return None

    result = try_with_model(primary_model, MODEL_NAME, attempts=2)
    if result is not None:
        return result

    log.warning("Primary model failed for %s, trying fallback model %s...", image_path.name, OCR_FALLBACK_MODEL_NAME)
    result = try_with_model(fallback_model, OCR_FALLBACK_MODEL_NAME, attempts=1)
    if result is not None:
        return result

    log.error("All attempts failed for %s, skipping.", image_path.name)
    return ""


def main():
    parser = argparse.ArgumentParser(description="OCR images using Gemini API")
    parser.add_argument(
        "--input-dir", "-i",
        default=None,
        type=Path,
        help=f"Directory containing images (default: {OUTPUT_BASE_DIR}/<author>__<title>)",
    )
    parser.add_argument(
        "--output-file", "-o",
        default=None,
        type=Path,
        help=f"Output JSON file (default: {OUTPUT_BASE_DIR}/<author>__<title>/ocr.json)",
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
    book_dir = Path(OUTPUT_BASE_DIR) / book_dir_name()
    if args.input_dir is None:
        args.input_dir = book_dir / "images"
    if args.output_file is None:
        args.output_file = book_dir / "ocr.json"
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

    try:
        configure_genai(args.api_key)
    except ValueError as e:
        log.error(e)
        return

    model = genai.GenerativeModel(MODEL_NAME)
    fallback_model = genai.GenerativeModel(OCR_FALLBACK_MODEL_NAME)

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

    results: List[Dict[str, Any]] = load_existing_results(args.output_file)
    done_files = {entry["file"] for entry in results}
    if done_files:
        log.info("Resuming: %d page(s) already processed, skipping them.", len(done_files))
        images = [img for img in images if img.name not in done_files]
        if not images:
            log.info("All pages already processed. Nothing to do.")
            return

    if args.start_page is not None or args.end_page is not None:
        log.info(
            "Found %d images to process in page range %s-%s",
            len(images),
            args.start_page if args.start_page is not None else "*",
            args.end_page if args.end_page is not None else "*",
        )
    else:
        log.info("Found %d images to process", len(images))

    save_lock = threading.Lock()
    args.output_file.parent.mkdir(parents=True, exist_ok=True)

    def process_image(img_path: Path):
        text = perform_ocr(img_path, model, fallback_model)
        if not text:
            log.warning("Skipping %s — no text extracted.", img_path.name)
            return
        entry = {"page": parse_page_num(img_path), "file": img_path.name, "text": text}
        with save_lock:
            results.append(entry)
            results.sort(key=lambda e: e["page"])
            with open(args.output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

    with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS) as executor:
        futures = [executor.submit(process_image, img) for img in images]
        for future in as_completed(futures):
            future.result()  # re-raise any unexpected exception

    log.info("OCR complete. Results saved to %s", args.output_file)


if __name__ == "__main__":
    main()
