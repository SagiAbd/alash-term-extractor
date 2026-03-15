#!/usr/bin/env python3
"""
run_batch.py — Sequential batch pipeline runner.

Reads a list of kazneb.kz URLs from .list.json and runs the full pipeline
(0 → 1 → 2 → 3 → rerun-failed) for each book in sequence.

If the output folder for a book already exists, the folder name in
.metadata.json is suffixed with _1, _2, etc. to avoid collisions.

Sound is played only once at the very end of the entire batch.

Usage:
    python3 run_batch.py
    python3 run_batch.py --list my_urls.json
    python3 run_batch.py --workers 15
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ROOT = Path(__file__).parent
METADATA_PATH = ROOT / ".metadata.json"
DEFAULT_LIST = ROOT / ".list.json"
OUTPUT_BASE = ROOT / "output"


def load_urls(list_path: Path) -> list[str]:
    data = json.loads(list_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{list_path} must contain a JSON array of URL strings")
    return [u.rstrip("#") for u in data if u.strip()]


def book_dir_name_from_meta() -> str:
    """Read .metadata.json and compute the folder name (mirrors config.book_dir_name)."""
    meta = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    author = meta.get("author") or ""
    title = meta.get("title") or ""

    def sanitize(s: str) -> str:
        s = re.sub(r'[/\\:*?"<>|]', '', s)
        s = re.sub(r'[\s,;]+', '_', s.strip())
        return s.strip('_')

    a = sanitize(author)
    t = sanitize(title)
    if a and t:
        return f"{a}__{t}"
    return a or t or "unknown"


def deduplicate_folder(base_name: str) -> str:
    """If output/<base_name> already exists, return base_name_1, _2, etc."""
    candidate = base_name
    counter = 1
    while (OUTPUT_BASE / candidate).exists():
        candidate = f"{base_name}_{counter}"
        counter += 1
    return candidate


def patch_metadata_title(suffix: str):
    """Append suffix to the title in .metadata.json so config.book_dir_name() returns the deduplicated name."""
    meta = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    meta["title"] = meta.get("title", "") + suffix
    METADATA_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Patched .metadata.json title → %s", meta["title"])


def run_step(script: str, args: list[str] | None = None):
    """Run a pipeline script, raising on failure."""
    cmd = [sys.executable, script] + (args or [])
    log.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        raise RuntimeError(f"{script} exited with code {result.returncode}")


def process_one(url: str, workers: int):
    """Run the full pipeline for a single URL."""
    log.info("=" * 60)
    log.info("STARTING: %s", url)
    log.info("=" * 60)

    # Step 0 — metadata
    run_step("0_metadata_scrape.py", ["--url", url])

    # Check for folder collision and deduplicate
    base_name = book_dir_name_from_meta()
    if (OUTPUT_BASE / base_name).exists():
        deduped = deduplicate_folder(base_name)
        # Figure out what suffix was added (e.g. "_1") and append to title
        suffix_part = deduped[len(base_name):]  # e.g. "_1"
        patch_metadata_title(suffix_part)
        log.info("Output folder exists — using deduplicated name: %s", deduped)

    # Step 1 — scrape
    run_step("1_scrape_parallel.py", ["--workers", str(workers)])

    # Step 2 — OCR
    run_step("2_ocr.py")

    # Step 3 — extract terms
    run_step("3_extract_terms.py")

    # Rerun failed pages
    log.info("Rerunning failed pages (if any)...")
    run_step("3_extract_terms.py", ["--rerun-failed"])

    log.info("COMPLETED: %s", url)


def main():
    parser = argparse.ArgumentParser(description="Batch pipeline runner")
    parser.add_argument(
        "--list", "-l",
        default=str(DEFAULT_LIST),
        help="Path to JSON file with list of URLs (default: .list.json)",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=20,
        help="Number of parallel workers for 1_scrape_parallel.py (default: 20)",
    )
    args = parser.parse_args()

    urls = load_urls(Path(args.list))
    log.info("Loaded %d URLs from %s", len(urls), args.list)

    failed = []
    for i, url in enumerate(urls, 1):
        log.info(">>> Book %d / %d", i, len(urls))
        try:
            process_one(url, args.workers)
        except Exception as e:
            log.error("FAILED on %s: %s", url, e)
            failed.append(url)

    log.info("=" * 60)
    log.info("BATCH COMPLETE: %d/%d succeeded", len(urls) - len(failed), len(urls))
    if failed:
        log.warning("Failed URLs:")
        for u in failed:
            log.warning("  %s", u)
    log.info("=" * 60)


if __name__ == "__main__":
    _t0 = time.time()
    main()
    _elapsed = time.time() - _t0
    log.info("Total batch time: %dm %02ds", int(_elapsed // 60), int(_elapsed % 60))
    # Play sound once at the very end
    _snd = ROOT / "done.mp3"
    if _snd.exists():
        os.system(f'afplay -t 10 "{_snd}"')
