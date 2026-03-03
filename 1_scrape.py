#!/usr/bin/env python3
"""
Selenium-based book page image scraper for kazneb.kz

Extracts book page images from the kazneb.kz online book viewer
by navigating through pages and downloading each page image.

Usage:
    python scraper.py
    python scraper.py --start-page 1 --end-page 10
    python scraper.py --url "https://kazneb.kz/la/bookView/view?brId=1597551&simple=true"
"""

import argparse
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DEFAULT_URL = "https://kazneb.kz/la/bookView/view?brId=1597551&simple=true"
DEFAULT_OUTPUT_DIR = "output"
PAGE_LOAD_TIMEOUT = 15  # seconds
IMAGE_CHANGE_TIMEOUT = 10  # seconds
MAX_RETRIES = 3


def create_driver(headless: bool = True) -> webdriver.Chrome:
    """Create and configure a Chrome WebDriver instance."""
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    # Avoid detection
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(30)
    return driver


def get_total_pages(driver: webdriver.Chrome) -> int:
    """Extract the total number of pages from the viewer."""
    # Method 1: "last page" button onclick — e.g. onNavigate(409)
    try:
        ffbtn = driver.find_element(By.CSS_SELECTOR, "a.ffbtn")
        onclick = ffbtn.get_attribute("onclick") or ""
        match = re.search(r"onNavigate\((\d+)\)", onclick)
        if match:
            total = int(match.group(1))
            log.info("Detected total pages from ffbtn onclick: %d", total)
            return total
    except Exception:
        pass

    # Method 2: JS pages array length
    try:
        total = driver.execute_script("return typeof pages !== 'undefined' ? pages.length : 0")
        if total and total > 0:
            log.info("Detected total pages from JS pages array: %d", total)
            return total
    except Exception:
        pass

    # Method 3: body text fallback
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        match = re.search(r"Total pages:\s*(\d+)", body_text)
        if match:
            return int(match.group(1))
    except Exception:
        pass

    log.warning("Could not detect total pages, defaulting to 999")
    return 999


def get_current_image_src(driver: webdriver.Chrome) -> str:
    """Get the current src attribute of the book page image."""
    try:
        img = driver.find_element(By.ID, "img")
        return img.get_attribute("src") or ""
    except Exception:
        return ""


def extract_page_number_from_src(src: str) -> int:
    """Extract the page number from the image URL (e.g., '0003.png' -> 3)."""
    match = re.search(r"/(\d{4})\.png", src)
    if match:
        return int(match.group(1))
    return -1


def wait_for_image_change(
    driver: webdriver.Chrome, old_src: str, timeout: float = IMAGE_CHANGE_TIMEOUT
) -> str:
    """Wait until the image src changes from old_src, return the new src."""
    start = time.time()
    while time.time() - start < timeout:
        new_src = get_current_image_src(driver)
        if new_src and new_src != old_src:
            # Give a tiny moment for the image element to stabilize
            time.sleep(0.3)
            return get_current_image_src(driver)
        time.sleep(0.3)
    raise TimeoutError(f"Image src did not change within {timeout}s")


def navigate_to_page(driver: webdriver.Chrome, page_num: int) -> str:
    """Navigate to a specific page number using the page input field."""
    old_src = get_current_image_src(driver)

    page_input = driver.find_element(By.ID, "pageNo")
    page_input.clear()
    page_input.send_keys(str(page_num))
    page_input.send_keys(Keys.RETURN)

    return wait_for_image_change(driver, old_src)


def click_next_page(driver: webdriver.Chrome) -> str:
    """Click the next-page button and wait for the image to change."""
    old_src = get_current_image_src(driver)

    next_btn = driver.find_element(By.CSS_SELECTOR, "a.fbtn")
    next_btn.click()

    return wait_for_image_change(driver, old_src)


def download_image(
    session: requests.Session, image_url: str, save_path: Path
) -> bool:
    """Download an image from the given URL and save to disk."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(image_url, timeout=30)
            resp.raise_for_status()

            if len(resp.content) < 1000:
                log.warning(
                    "Image too small (%d bytes), might be an error page",
                    len(resp.content),
                )

            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(resp.content)
            return True
        except Exception as e:
            log.warning("Download attempt %d failed: %s", attempt, e)
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
    return False


def transfer_cookies(driver: webdriver.Chrome, session: requests.Session):
    """Copy cookies from the Selenium browser to a requests Session."""
    for cookie in driver.get_cookies():
        session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"))


def scrape_pages(
    url: str,
    output_dir: str,
    start_page: int,
    end_page: int | None,
    headless: bool = True,
    delay: float = 1.0,
):
    """
    Main scraping loop.

    Args:
        url:        The book viewer URL.
        output_dir: Directory to save downloaded images.
        start_page: First page to download (1-indexed).
        end_page:   Last page to download (inclusive). None = all pages.
        headless:   Run Chrome in headless mode.
        delay:      Seconds to wait between page downloads.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    log.info("Starting scraper...")
    driver = create_driver(headless=headless)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": driver.execute_script("return navigator.userAgent"),
            "Referer": url,
        }
    )

    try:
        # --- Load the viewer page ---
        log.info("Loading viewer: %s", url)
        driver.get(url)
        WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
            EC.presence_of_element_located((By.ID, "img"))
        )
        time.sleep(2)  # let JS settle

        # --- Detect total pages ---
        total = get_total_pages(driver)
        if end_page is None or end_page > total:
            end_page = total
        log.info("Total pages: %d | Downloading pages %d–%d", total, start_page, end_page)

        # --- Transfer cookies for image downloads ---
        transfer_cookies(driver, session)

        # --- Navigate to start page if needed ---
        if start_page > 1:
            log.info("Jumping to page %d...", start_page)
            navigate_to_page(driver, start_page)
            time.sleep(1)

        # --- Main download loop ---
        for page_num in range(start_page, end_page + 1):
            img_src = get_current_image_src(driver)
            if not img_src:
                log.error("Page %d: no image src found, skipping", page_num)
                continue

            file_name = f"{page_num:04d}.png"
            save_file = out_path / file_name

            if save_file.exists():
                log.info("Page %d: already exists, skipping", page_num)
            else:
                success = download_image(session, img_src, save_file)
                if success:
                    log.info("Page %d: saved → %s", page_num, save_file)
                else:
                    log.error("Page %d: FAILED to download", page_num)

            # Advance to next page (unless we're on the last one)
            if page_num < end_page:
                try:
                    click_next_page(driver)
                except TimeoutError:
                    log.warning(
                        "Page %d: timed out waiting for next page, retrying via page input",
                        page_num,
                    )
                    try:
                        navigate_to_page(driver, page_num + 1)
                    except TimeoutError:
                        log.error("Page %d: could not advance, stopping.", page_num)
                        break

                time.sleep(delay)

        log.info("Done! Images saved to: %s", out_path.resolve())

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    except Exception as e:
        log.exception("Fatal error: %s", e)
    finally:
        driver.quit()
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Download book page images from kazneb.kz"
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Book viewer URL (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for images (default: %(default)s)",
    )
    parser.add_argument(
        "--start-page", "-s",
        type=int,
        default=1,
        help="First page number to download (default: 1)",
    )
    parser.add_argument(
        "--end-page", "-e",
        type=int,
        default=None,
        help="Last page number to download (default: all pages)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Show the browser window (useful for debugging)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between pages in seconds (default: 1.0)",
    )

    args = parser.parse_args()
    scrape_pages(
        url=args.url,
        output_dir=args.output_dir,
        start_page=args.start_page,
        end_page=args.end_page,
        headless=not args.no_headless,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
