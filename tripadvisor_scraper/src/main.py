from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .scraper import START_URL, TripadvisorScraper, create_default_storage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Tripadvisor Milan listing pages into normalized JSON.")
    parser.add_argument("--start-url", default=START_URL, help="Tripadvisor Milan listing URL to start from.")
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
    parser.add_argument(
        "--user-data-dir",
        default=None,
        help="Persistent browser profile directory, for example output/browser_profile.",
    )
    parser.add_argument(
        "--manual-unlock",
        action="store_true",
        help="Keep the browser open and wait for manual DataDome or captcha unlock when needed.",
    )
    parser.add_argument(
        "--unlock-timeout-seconds",
        type=int,
        default=300,
        help="Maximum time to wait for manual unlock.",
    )
    parser.add_argument(
        "--save-session-only",
        action="store_true",
        help="Open the listing and save the persistent browser session without scraping JSON output.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Load the partial JSON and continue from the next source page.",
    )
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
    if args.save_session_only and not args.manual_unlock:
        logging.info("Enabling manual unlock mode because --save-session-only was requested.")
        args.manual_unlock = True

    user_data_dir = resolve_user_data_dir(project_root, args.user_data_dir, args.manual_unlock)
    storage = create_default_storage(project_root)
    scraper = TripadvisorScraper(
        storage=storage,
        start_url=args.start_url,
        browser_channel=args.browser_channel,
        headless=not args.headed,
        delay_seconds=args.delay_seconds,
        partial_every_pages=args.partial_every_pages,
        user_data_dir=user_data_dir,
        manual_unlock=args.manual_unlock,
        unlock_timeout_seconds=args.unlock_timeout_seconds,
        save_session_only=args.save_session_only,
        resume=args.resume,
    )

    try:
        records = scraper.scrape(max_pages=args.max_pages)
    except RuntimeError as error:
        logging.error("%s", error)
        raise SystemExit(1)

    logging.info("Scraping completed with %s normalized restaurant records.", len(records))


def resolve_user_data_dir(project_root: Path, raw_user_data_dir: str | None, manual_unlock: bool) -> Path | None:
    if raw_user_data_dir is None:
        if not manual_unlock:
            return None
        return project_root / "output" / "browser_profile"

    user_data_dir = Path(raw_user_data_dir)
    if user_data_dir.is_absolute():
        return user_data_dir
    return project_root / user_data_dir


if __name__ == "__main__":
    main()
