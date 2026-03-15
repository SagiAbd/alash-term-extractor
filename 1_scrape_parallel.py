#!/usr/bin/env python3
"""
Parallel wrapper for 1_scrape.py

Splits total pages into N chunks and runs N instances of 1_scrape.py
simultaneously, each writing to a temp subdirectory.
After all workers finish, merges all images into the final output directory.

Usage:
    python3 1_scrape_parallel.py
    python3 1_scrape_parallel.py --workers 10
    python3 1_scrape_parallel.py --url "https://kazneb.kz/..." --total-pages 300
    python3 1_scrape_parallel.py --workers 5 --start-page 1 --end-page 100
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from config import (
    SCRAPER_DEFAULT_URL as DEFAULT_URL,
    OUTPUT_BASE_DIR,
    book_dir_name,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

METADATA_FILE = Path(__file__).parent / ".metadata.json"


def get_total_pages_from_metadata() -> int | None:
    if METADATA_FILE.exists():
        try:
            data = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
            return data.get("total_pages")
        except Exception:
            pass
    return None


def run_worker(worker_id: int, cmd: list[str]) -> tuple[int, int]:
    """Run a single 1_scrape.py instance. Returns (worker_id, returncode)."""
    log.info("Worker %d starting: pages %s–%s", worker_id, cmd[cmd.index("--start-page") + 1], cmd[cmd.index("--end-page") + 1])
    result = subprocess.run(cmd, capture_output=False)
    log.info("Worker %d finished (exit %d)", worker_id, result.returncode)
    return worker_id, result.returncode


def main():
    parser = argparse.ArgumentParser(description="Run 1_scrape.py in parallel chunks")
    parser.add_argument("--url", default=DEFAULT_URL, help="Book viewer URL")
    parser.add_argument("--workers", "-w", type=int, default=20, help="Number of parallel instances (default: 20)")
    parser.add_argument("--total-pages", type=int, default=None, help="Total pages (auto-detected from .metadata.json if omitted)")
    parser.add_argument("--start-page", type=int, default=1, help="First page (default: 1)")
    parser.add_argument("--end-page", type=int, default=None, help="Last page (default: all)")
    parser.add_argument("--no-headless", action="store_true", help="Show browser windows")
    parser.add_argument("--output-dir", "-o", default=None, help="Final output directory for images")
    args = parser.parse_args()

    # --- Resolve total pages ---
    total_pages = args.total_pages or get_total_pages_from_metadata()
    if not total_pages:
        log.error("Could not determine total pages. Run 0_metadata_scrape.py first, or pass --total-pages N.")
        sys.exit(1)

    start = args.start_page
    end = args.end_page or total_pages
    final_output = args.output_dir or str(Path(OUTPUT_BASE_DIR) / book_dir_name() / "images")
    final_path = Path(final_output)

    log.info("Pages %d–%d split across %d workers → %s", start, end, args.workers, final_path)

    # --- Split page range into chunks ---
    total = end - start + 1
    chunk = max(1, total // args.workers)
    chunks = []
    cur = start
    for i in range(args.workers):
        chunk_end = cur + chunk - 1 if i < args.workers - 1 else end
        if cur > end:
            break
        chunks.append((cur, min(chunk_end, end)))
        cur = chunk_end + 1

    log.info("Chunks: %s", chunks)

    # --- Create per-worker temp dirs ---
    tmp_base = final_path.parent / "_tmp_scrape"
    tmp_dirs = []
    for i, (s, e) in enumerate(chunks):
        td = tmp_base / f"worker_{i+1:02d}"
        td.mkdir(parents=True, exist_ok=True)
        tmp_dirs.append(td)

    # --- Build subprocess commands ---
    python = sys.executable
    scraper = str(Path(__file__).parent / "1_scrape.py")
    commands = []
    for i, (s, e) in enumerate(chunks):
        cmd = [
            python, scraper,
            "--url", args.url,
            "--start-page", str(s),
            "--end-page", str(e),
            "--output-dir", str(tmp_dirs[i]),
        ]
        if args.no_headless:
            cmd.append("--no-headless")
        commands.append((i + 1, cmd))

    # --- Run workers in parallel ---
    failed_workers = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_worker, wid, cmd): wid for wid, cmd in commands}
        for future in as_completed(futures):
            wid, returncode = future.result()
            if returncode != 0:
                failed_workers.append(wid)

    if failed_workers:
        log.warning("Workers with errors: %s", failed_workers)

    # --- Merge all temp dirs into final output ---
    log.info("Merging images into: %s", final_path)
    final_path.mkdir(parents=True, exist_ok=True)
    merged = 0
    for td in tmp_dirs:
        for img in sorted(td.glob("*.png")):
            dest = final_path / img.name
            shutil.move(str(img), str(dest))
            merged += 1

    # Cleanup temp dirs
    shutil.rmtree(tmp_base, ignore_errors=True)

    log.info("Done. %d images merged into %s", merged, final_path.resolve())


if __name__ == "__main__":
    _t0 = time.time()
    main()
    _elapsed = time.time() - _t0
    log.info("Total time: %dm %02ds", int(_elapsed // 60), int(_elapsed % 60))
    if os.environ.get("PLAY_SOUND", "").lower() in ("1", "true", "yes"):
        _snd = Path(__file__).parent / "done.mp3"
        if _snd.exists():
            os.system(f'afplay -t 10 "{_snd}"')
