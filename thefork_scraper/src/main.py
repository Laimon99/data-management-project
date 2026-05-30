from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .scraper import START_URL, TheForkScraper, create_default_storage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape TheFork Milan listing pages into normalized JSON.")
    parser.add_argument("--start-url", default=START_URL, help="TheFork Milan listing URL to start from.")
    parser.add_argument("--max-pages", type=int, default=None, help="Maximum number of listing pages to scrape.")
    parser.add_argument("--delay-seconds", type=float, default=1.5, help="Delay between listing pages.")
    parser.add_argument(
        "--partial-every-pages",
        type=int,
        default=5,
        help="Save partial progress every N processed pages.",
    )
    parser.add_argument(
        "--browser-channel",
        default=None,
        help="Optional Playwright Chromium channel, for example chrome, msedge, or chromium.",
    )
    parser.add_argument("--headed", action="store_true", help="Run the browser with a visible window.")
    parser.add_argument("--log-level", default="INFO", help="Logging level, for example INFO or DEBUG.")
    return parser.parse_args()


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    project_root = Path(__file__).resolve().parents[1]
    storage = create_default_storage(project_root)
    scraper = TheForkScraper(
        storage=storage,
        start_url=args.start_url,
        browser_channel=args.browser_channel,
        headless=not args.headed,
        delay_seconds=args.delay_seconds,
        partial_every_pages=args.partial_every_pages,
    )

    records = scraper.scrape(max_pages=args.max_pages)
    logging.info("Scraping completed with %s normalized restaurant records.", len(records))


if __name__ == "__main__":
    main()

