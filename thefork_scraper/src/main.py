from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import config
from .calibration import CalibrationOptions, run_detail_block_calibration
from .proxy_utils import build_proxy_configs
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
        "--detail-delay-min-seconds",
        type=float,
        default=None,
        help="Minimum random delay between detail pages. Overrides the fixed detail delay when set.",
    )
    parser.add_argument(
        "--detail-delay-max-seconds",
        type=float,
        default=None,
        help="Maximum random delay between detail pages. Overrides the fixed detail delay when set.",
    )
    parser.add_argument(
        "--human-detail-scroll",
        action="store_true",
        help="Perform a light human-like scroll before extracting detail page fields.",
    )
    parser.add_argument(
        "--pause-on-antibot",
        action="store_true",
        help="Pause for manual captcha/anti-bot solving before retrying a blocked detail page.",
    )
    parser.add_argument(
        "--micro-pause-min-ms",
        type=int,
        default=0,
        help="Minimum short random pause before each detail page attempt, in milliseconds.",
    )
    parser.add_argument(
        "--micro-pause-max-ms",
        type=int,
        default=0,
        help="Maximum short random pause before each detail page attempt, in milliseconds.",
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
        "--proxy-burn-through",
        action="store_true",
        help="Use each proxy until it stops producing detail records, then retire it and move to the next proxy.",
    )
    parser.add_argument(
        "--proxy-round-robin",
        action="store_true",
        help="Rotate proxies after a small number of detail pages and rest each proxy before reuse.",
    )
    parser.add_argument(
        "--restaurants-per-proxy-turn",
        type=int,
        default=1,
        help="Maximum detail pages to scrape with one proxy before rotating to the next proxy.",
    )
    parser.add_argument(
        "--proxy-min-rest-seconds",
        type=float,
        default=90.0,
        help="Minimum rest time before the same proxy can be reused in round-robin mode.",
    )
    parser.add_argument(
        "--proxy-max-failed-turns",
        type=int,
        default=3,
        help="Retire a proxy after this many consecutive round-robin turns without a completed detail record.",
    )
    parser.add_argument(
        "--proxy-turn-jitter-seconds",
        type=float,
        default=5.0,
        help="Random delay added between round-robin proxy turns.",
    )
    parser.add_argument(
        "--include-direct-ip-after-proxies",
        action="store_true",
        help="After all proxies are retired, continue burn-through mode with the direct IP.",
    )
    parser.add_argument(
        "--detail-batch-size",
        type=int,
        default=config.DETAIL_BATCH_SIZE,
        help="Maximum number of missing detail pages to process before reopening the browser.",
    )
    parser.add_argument(
        "--detail-shard-count",
        type=int,
        default=1,
        help="Split missing detail pages across this many teammate runs.",
    )
    parser.add_argument(
        "--detail-shard-index",
        type=int,
        default=1,
        help="One-based shard number for this run, between 1 and --detail-shard-count.",
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
        default="output",
        help="Directory for final, partial, and validation JSON files.",
    )
    parser.add_argument(
        "--input-partial",
        default=None,
        help="Optional existing partial JSON used as the starting point for a separate output dir.",
    )
    parser.add_argument(
        "--browser-channel",
        default=None,
        help="Optional Playwright Chromium channel, for example chrome, msedge, or chromium.",
    )
    parser.add_argument(
        "--browser-executable-path",
        default=None,
        help="Optional explicit Chromium-compatible browser path, for example Brave.",
    )
    parser.add_argument("--proxy-list", default=None, help="Path to a text file with one proxy URL per line.")
    parser.add_argument("--proxy-server", default=None, help="Single proxy server, for example http://host:port.")
    parser.add_argument("--proxy-username", default=None, help="Username for --proxy-server.")
    parser.add_argument("--proxy-password", default=None, help="Password for --proxy-server.")
    parser.add_argument(
        "--user-data-dir",
        default=None,
        help="Persistent browser profile directory, for example output/browser_profile.",
    )
    parser.add_argument(
        "--calibrate-detail-blocks",
        action="store_true",
        help="Run controlled detail-page block calibration and save reports without changing the main partial JSON.",
    )
    parser.add_argument(
        "--calibration-output-dir",
        default="output/calibration",
        help="Directory where calibration reports and sample records are saved.",
    )
    parser.add_argument(
        "--calibration-max-records",
        type=int,
        default=10,
        help="Maximum missing detail records used by each calibration run. Use 0 for estimate-only mode.",
    )
    parser.add_argument(
        "--calibration-delay-seconds",
        default=None,
        help="Comma-separated detail delays to test, for example 5,10,20.",
    )
    parser.add_argument(
        "--calibration-batch-size",
        type=int,
        default=10,
        help="Maximum records attempted in a single calibration browser session.",
    )
    parser.add_argument(
        "--calibration-time-budget-hours",
        type=float,
        default=20.0,
        help="Target maximum total scraping time used in proxy estimates.",
    )
    parser.add_argument(
        "--calibration-max-proxies",
        type=int,
        default=10,
        help="Maximum number of proxies considered in estimates and proxy tests.",
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
    if args.detail_shard_count < 1:
        raise SystemExit("--detail-shard-count must be at least 1.")
    if args.detail_shard_index < 1 or args.detail_shard_index > args.detail_shard_count:
        raise SystemExit("--detail-shard-index must be between 1 and --detail-shard-count.")

    project_root = Path(__file__).resolve().parents[1]
    user_data_dir = resolve_user_data_dir(project_root, args.user_data_dir, bool(args.proxy_list or args.proxy_server))
    proxy_configs = build_proxy_configs(
        proxy_list_path=resolve_optional_path(project_root, args.proxy_list),
        proxy_server=args.proxy_server,
        proxy_username=args.proxy_username,
        proxy_password=args.proxy_password,
    )
    storage = create_default_storage(project_root, args.output_dir, args.input_partial)

    if args.calibrate_detail_blocks:
        calibration_options = CalibrationOptions(
            output_dir=resolve_output_dir(project_root, args.calibration_output_dir),
            browser_channel=args.browser_channel,
            headless=not args.headed,
            delay_values=parse_delay_values(args.calibration_delay_seconds, args.detail_delay_seconds),
            max_records=args.calibration_max_records,
            batch_size=args.calibration_batch_size,
            max_consecutive_failures=args.max_consecutive_detail_failures,
            proxy_configs=proxy_configs,
            max_proxies=args.calibration_max_proxies,
            time_budget_hours=args.calibration_time_budget_hours,
            cooldown_seconds=args.cooldown_seconds,
            user_data_dir=user_data_dir,
        )
        run_detail_block_calibration(storage, calibration_options)
        return

    scraper = TheForkScraper(
        storage=storage,
        start_url=args.start_url,
        browser_channel=args.browser_channel,
        browser_executable_path=args.browser_executable_path,
        headless=not args.headed,
        delay_seconds=args.delay_seconds,
        detail_delay_seconds=args.detail_delay_seconds,
        detail_delay_min_seconds=args.detail_delay_min_seconds,
        detail_delay_max_seconds=args.detail_delay_max_seconds,
        human_scroll_enabled=args.human_detail_scroll,
        pause_on_antibot=args.pause_on_antibot,
        micro_pause_min_ms=args.micro_pause_min_ms,
        micro_pause_max_ms=args.micro_pause_max_ms,
        partial_every_pages=args.partial_every_pages,
        partial_every_restaurants=args.partial_every_restaurants,
        scrape_detail_pages=not args.no_detail_pages,
        resume_detail=args.resume_detail,
        max_consecutive_detail_failures=args.max_consecutive_detail_failures,
        auto_detail_until_complete=args.auto_detail_until_complete,
        detail_batch_size=args.detail_batch_size,
        detail_shard_count=args.detail_shard_count,
        detail_shard_index=args.detail_shard_index,
        cooldown_seconds=args.cooldown_seconds,
        max_cooldown_seconds=args.max_cooldown_seconds,
        cooldown_multiplier=args.cooldown_multiplier,
        max_auto_detail_cycles=args.max_auto_detail_cycles,
        save_final_incomplete=args.save_final_incomplete,
        proxy_configs=proxy_configs,
        user_data_dir=user_data_dir,
        proxy_burn_through=args.proxy_burn_through,
        include_direct_ip_after_proxies=args.include_direct_ip_after_proxies,
        proxy_round_robin=args.proxy_round_robin,
        restaurants_per_proxy_turn=args.restaurants_per_proxy_turn,
        proxy_min_rest_seconds=args.proxy_min_rest_seconds,
        proxy_max_failed_turns=args.proxy_max_failed_turns,
        proxy_turn_jitter_seconds=args.proxy_turn_jitter_seconds,
    )

    records = scraper.scrape(max_pages=args.max_pages, max_restaurants=args.max_restaurants)
    logging.info("Scraping completed with %s normalized restaurant records.", len(records))


def resolve_optional_path(project_root: Path, raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)
    return str(project_root / path)


def resolve_user_data_dir(project_root: Path, raw_user_data_dir: str | None, use_default: bool) -> Path | None:
    if raw_user_data_dir is None:
        if not use_default:
            return None
        return project_root / "output" / "browser_profile"
    user_data_dir = Path(raw_user_data_dir)
    if user_data_dir.is_absolute():
        return user_data_dir
    return project_root / user_data_dir


def resolve_output_dir(project_root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return project_root / path


def parse_delay_values(raw_value: str | None, fallback: float) -> list[float]:
    if not raw_value:
        return [fallback]
    values: list[float] = []
    for item in raw_value.split(","):
        text = item.strip()
        if not text:
            continue
        values.append(float(text))
    return values or [fallback]


if __name__ == "__main__":
    main()
