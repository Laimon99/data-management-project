from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import config
from .scraper import START_URL, TheForkScraper, create_default_storage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape TheFork Milan listing pages into normalized JSON.")
    parser.add_argument("--start-url", default=START_URL, help="TheFork Milan listing URL to start from.")
    parser.add_argument("--max-pages", type=int, default=config.MAX_LISTING_PAGES, help="Maximum number of listing pages to scrape.")
    parser.add_argument("--max-restaurants", type=int, default=config.MAX_RESTAURANTS, help="Maximum number of restaurants to enrich.")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=config.DELAY_BETWEEN_LISTING_PAGES_SECONDS,
        help="Delay between listing pages.",
    )
    parser.add_argument(
        "--detail-delay-seconds",
        type=float,
        default=config.DELAY_BETWEEN_DETAIL_PAGES_SECONDS,
        help="Delay between detail pages.",
    )
    parser.add_argument(
        "--partial-every-pages",
        type=int,
        default=5,
        help="Save partial progress every N processed pages.",
    )
    parser.add_argument(
        "--partial-every-restaurants",
        type=int,
        default=config.SAVE_PARTIAL_EVERY_N_RESTAURANTS,
        help="Save partial progress every N enriched restaurants.",
    )
    parser.add_argument(
        "--no-detail-pages",
        action="store_true",
        help="Only scrape listing pages and skip restaurant detail pages.",
    )
    parser.add_argument(
        "--resume-detail",
        action="store_true",
        help="Load the partial JSON and continue enriching records that do not have detail_scraped=true.",
    )
    parser.add_argument(
        "--max-consecutive-detail-failures",
        type=int,
        default=10,
        help="Stop detail scraping after this many consecutive detail-page failures.",
    )
    parser.add_argument(
        "--auto-detail-until-complete",
        action="store_true",
        help="Keep retrying missing detail pages with cooldowns until all records are complete.",
    )
    parser.add_argument(
        "--detail-batch-size",
        type=int,
        default=config.DETAIL_BATCH_SIZE,
        help="Maximum number of missing detail pages to process before reopening the browser.",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=int,
        default=config.COOLDOWN_SECONDS,
        help="Initial cooldown after a blocked detail batch.",
    )
    parser.add_argument(
        "--max-cooldown-seconds",
        type=int,
        default=config.MAX_COOLDOWN_SECONDS,
        help="Maximum cooldown after repeated blocked batches.",
    )
    parser.add_argument(
        "--cooldown-multiplier",
        type=float,
        default=config.COOLDOWN_MULTIPLIER,
        help="Multiplier applied to cooldown after repeated blocked batches.",
    )
    parser.add_argument(
        "--max-auto-detail-cycles",
        type=int,
        default=config.MAX_AUTO_DETAIL_CYCLES,
        help="Maximum number of automatic detail retry cycles.",
    )
    parser.add_argument(
        "--save-final-incomplete",
        action="store_true",
        help="Allow writing the final JSON even if some detail pages are still incomplete.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/raw/thefork",
        help="Directory for final, partial, and validation JSON files.",
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

    # services/thefork_scraper_extract/main.py -> repo root is three levels up,
    # so default --output-dir "data/raw/thefork" resolves under the repo data dir.
    project_root = Path(__file__).resolve().parents[2]
    storage = create_default_storage(project_root, args.output_dir)
    scraper = TheForkScraper(
        storage=storage,
        start_url=args.start_url,
        browser_channel=args.browser_channel,
        headless=not args.headed,
        delay_seconds=args.delay_seconds,
        detail_delay_seconds=args.detail_delay_seconds,
        partial_every_pages=args.partial_every_pages,
        partial_every_restaurants=args.partial_every_restaurants,
        scrape_detail_pages=not args.no_detail_pages,
        resume_detail=args.resume_detail,
        max_consecutive_detail_failures=args.max_consecutive_detail_failures,
        auto_detail_until_complete=args.auto_detail_until_complete,
        detail_batch_size=args.detail_batch_size,
        cooldown_seconds=args.cooldown_seconds,
        max_cooldown_seconds=args.max_cooldown_seconds,
        cooldown_multiplier=args.cooldown_multiplier,
        max_auto_detail_cycles=args.max_auto_detail_cycles,
        save_final_incomplete=args.save_final_incomplete,
    )

    records = scraper.scrape(max_pages=args.max_pages, max_restaurants=args.max_restaurants)
    logging.info("Scraping completed with %s normalized restaurant records.", len(records))


if __name__ == "__main__":
    main()
