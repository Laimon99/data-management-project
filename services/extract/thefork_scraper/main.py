from __future__ import annotations

import argparse
import logging
import os
import shutil
from pathlib import Path

from . import config
from .calibration import CalibrationOptions, run_detail_block_calibration
from .cdp_parallel import (
    ParallelCDPOptions,
    default_parallel_profile_root,
    run_parallel_graphql_cdp,
)
from .graphql_detail_scraper import GraphQLDetailOptions, run_graphql_detail_enrichment
from .proxy_utils import build_proxy_configs
from .scraper import START_URL, TheForkScraper, create_default_storage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape TheFork Milan listing pages into normalized JSON."
    )
    parser.add_argument(
        "--start-url", default=START_URL, help="TheFork Milan listing URL to start from."
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=config.MAX_LISTING_PAGES,
        help="Maximum number of listing pages to scrape.",
    )
    parser.add_argument(
        "--max-restaurants",
        type=int,
        default=config.MAX_RESTAURANTS,
        help="Maximum number of restaurants to enrich.",
    )
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
        default=60.0,
        help=(
            "Minimum random delay between detail pages. Overrides the fixed detail delay when set."
        ),
    )
    parser.add_argument(
        "--detail-delay-max-seconds",
        type=float,
        default=180.0,
        help=(
            "Maximum random delay between detail pages. Overrides the fixed detail delay when set."
        ),
    )
    parser.add_argument(
        "--human-detail-scroll",
        action="store_true",
        help="Perform a light human-like scroll before extracting detail page fields.",
    )
    parser.add_argument(
        "--pause-on-antibot",
        action="store_true",
        help=(
            "Pause for manual browser intervention when a detail page shows "
            "HTTP 403/429 or anti-bot markers."
        ),
    )
    parser.add_argument(
        "--micro-pause-min-ms",
        type=int,
        default=0,
        help="Minimum human-like micro-pause before detail extraction.",
    )
    parser.add_argument(
        "--micro-pause-max-ms",
        type=int,
        default=0,
        help="Maximum human-like micro-pause before detail extraction.",
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
        help=(
            "Load the partial JSON and continue enriching records "
            "that do not have detail_scraped=true."
        ),
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
        help=(
            "Use each proxy until it stops producing detail records, "
            "then retire it and move to the next proxy."
        ),
    )
    parser.add_argument(
        "--proxy-round-robin",
        action="store_true",
        help=(
            "Rotate proxies after a small number of detail pages and rest each proxy before reuse."
        ),
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
        default=900.0,
        help="Minimum rest time before the same proxy can be reused in round-robin mode.",
    )
    parser.add_argument(
        "--proxy-403-cooldown-seconds",
        type=float,
        default=10800.0,
        help=(
            "Cooldown applied to a proxy after a detail page returns HTTP 403 in round-robin mode."
        ),
    )
    parser.add_argument(
        "--pool-403-threshold",
        type=int,
        default=3,
        help=(
            "Stop round-robin mode when this many distinct proxies return HTTP 403 "
            "inside the pool window."
        ),
    )
    parser.add_argument(
        "--pool-403-window-seconds",
        type=float,
        default=900.0,
        help="Rolling time window used to count distinct proxies returning HTTP 403.",
    )
    parser.add_argument(
        "--pool-403-cooldown-seconds",
        type=float,
        default=21600.0,
        help="Global cooldown stored after the proxy pool reaches the HTTP 403 threshold.",
    )
    parser.add_argument(
        "--stop-on-pool-block",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Stop the current run when the proxy pool reaches the HTTP 403 threshold.",
    )
    parser.add_argument(
        "--proxy-max-failed-turns",
        type=int,
        default=3,
        help=(
            "Retire a proxy after this many consecutive round-robin turns "
            "without a completed detail record."
        ),
    )
    parser.add_argument(
        "--proxy-turn-jitter-seconds",
        type=float,
        default=30.0,
        help="Random delay added between round-robin proxy turns.",
    )
    parser.add_argument(
        "--max-url-failures-before-deferral",
        type=int,
        default=1,
        help="Temporarily skip a detail URL after this many failed attempts across proxy turns.",
    )
    parser.add_argument(
        "--deferred-url-retry-cycles",
        type=int,
        default=300,
        help="Number of round-robin cycles to wait before retrying a deferred detail URL.",
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
        help="Split missing detail pages across this many parallel runs.",
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
        default="data/raw/thefork",
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
    parser.add_argument(
        "--brave-automation-profile",
        action="store_true",
        help=(
            "Use Brave Browser with a headed persistent automation profile. "
            "Defaults --user-data-dir to data/raw/thefork/brave_automation_profile."
        ),
    )
    parser.add_argument(
        "--browser-warmup-url",
        default=None,
        help="Optional URL to open before detail scraping to warm up a persistent browser profile.",
    )
    parser.add_argument(
        "--browser-warmup-seconds",
        type=float,
        default=None,
        help="Seconds to wait on the warm-up URL before detail scraping.",
    )
    parser.add_argument(
        "--connect-over-cdp-url",
        default=None,
        help="Connect to an already-open Chromium/Brave instance, for example http://127.0.0.1:9222.",
    )
    parser.add_argument(
        "--graphql-detail-from-cdp",
        action="store_true",
        help=(
            "Resume missing detail enrichment through TheFork GraphQL calls executed "
            "inside an already-open manual Brave/Chromium tab connected with "
            "--connect-over-cdp-url."
        ),
    )
    parser.add_argument(
        "--graphql-review-size",
        type=int,
        default=None,
        help=(
            "Maximum reviews to request per restaurant in --graphql-detail-from-cdp mode. "
            "Defaults to --max-reviews-per-restaurant."
        ),
    )
    parser.add_argument(
        "--max-reviews-per-restaurant",
        type=int,
        default=config.MAX_REVIEWS_PER_RESTAURANT,
        help="Maximum review objects to keep per restaurant in non-GraphQL detail mode.",
    )
    parser.add_argument(
        "--graphql-cdp-parallel-proxies",
        action="store_true",
        help="Launch multiple Brave proxy profiles and run parallel GraphQL/CDP detail workers.",
    )
    parser.add_argument(
        "--parallel-workers",
        type=int,
        default=2,
        help=(
            "Number of Brave proxy profiles / GraphQL workers to run "
            "in --graphql-cdp-parallel-proxies mode."
        ),
    )
    parser.add_argument(
        "--parallel-base-port",
        type=int,
        default=9222,
        help="First local CDP port used by parallel Brave profiles.",
    )
    parser.add_argument(
        "--parallel-profile-root",
        default=None,
        help=(
            "Directory for parallel Brave user data dirs. "
            "Defaults to C:/tmp/thefork_cdp_proxy_profiles on Windows."
        ),
    )
    parser.add_argument(
        "--parallel-output-root",
        default="data/raw/thefork/runs/graphql_cdp_parallel",
        help=(
            "Base output directory for parallel GraphQL/CDP runs. "
            "Each execution creates a fresh run_YYYYMMDD_HHMMSS subdirectory."
        ),
    )
    parser.add_argument(
        "--parallel-prepare-only",
        action="store_true",
        help=(
            "Launch the Brave proxy profiles and print worker commands, "
            "but do not start scraping workers."
        ),
    )
    parser.add_argument(
        "--parallel-dry-run",
        action="store_true",
        help="Print the parallel plan without launching browsers or workers.",
    )
    parser.add_argument(
        "--parallel-no-manual-wait",
        action="store_true",
        help=(
            "Start workers immediately after CDP ports are ready "
            "instead of waiting for manual TheFork checks."
        ),
    )
    parser.add_argument(
        "--parallel-no-auto-merge",
        action="store_true",
        help=(
            "Do not merge worker partial files back into the input partial "
            "after parallel workers finish."
        ),
    )
    parser.add_argument(
        "--distributed-slot-count",
        type=int,
        default=None,
        help=(
            "Total zero-based detail slots shared across multiple PCs. "
            "When omitted, local workers split only with each other."
        ),
    )
    parser.add_argument(
        "--distributed-slot-start",
        type=int,
        default=0,
        help="Zero-based global slot assigned to the first local parallel worker.",
    )
    parser.add_argument(
        "--proxy-list", default=None, help="Path to a text file with one proxy URL per line."
    )
    parser.add_argument(
        "--proxy-server", default=None, help="Single proxy server, for example http://host:port."
    )
    parser.add_argument("--proxy-username", default=None, help="Username for --proxy-server.")
    parser.add_argument("--proxy-password", default=None, help="Password for --proxy-server.")
    parser.add_argument(
        "--user-data-dir",
        default=None,
        help="Persistent browser profile directory, for example data/raw/thefork/browser_profile.",
    )
    parser.add_argument(
        "--calibrate-detail-blocks",
        action="store_true",
        help=(
            "Run controlled detail-page block calibration and save reports "
            "without changing the main partial JSON."
        ),
    )
    parser.add_argument(
        "--calibration-output-dir",
        default="data/raw/thefork/calibration",
        help="Directory where calibration reports and sample records are saved.",
    )
    parser.add_argument(
        "--calibration-max-records",
        type=int,
        default=10,
        help=(
            "Maximum missing detail records used by each calibration run. "
            "Use 0 for estimate-only mode."
        ),
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
    parser.add_argument(
        "--headed", action="store_true", help="Run the browser with a visible window."
    )
    parser.add_argument(
        "--log-level", default="INFO", help="Logging level, for example INFO or DEBUG."
    )
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
    if args.distributed_slot_count is not None and args.distributed_slot_count < 1:
        raise SystemExit("--distributed-slot-count must be at least 1.")
    if args.distributed_slot_start < 0:
        raise SystemExit("--distributed-slot-start must be zero or greater.")
    if args.graphql_review_size is None:
        args.graphql_review_size = args.max_reviews_per_restaurant

    # This package lives under services/<name>/, so the repo root is parents[2];
    # default --output-dir "data/raw/thefork" then resolves under the repo data dir.
    project_root = Path(__file__).resolve().parents[2]
    browser_executable_path = resolve_browser_executable_path(
        args.browser_executable_path,
        args.brave_automation_profile,
    )
    headless = not (args.headed or args.brave_automation_profile)
    browser_warmup_url = args.browser_warmup_url or (
        args.start_url if args.brave_automation_profile else None
    )
    browser_warmup_seconds = (
        args.browser_warmup_seconds
        if args.browser_warmup_seconds is not None
        else (30.0 if args.brave_automation_profile else 0.0)
    )
    user_data_dir = resolve_user_data_dir(
        project_root,
        args.user_data_dir,
        bool(args.proxy_list or args.proxy_server or args.brave_automation_profile),
        "brave_automation_profile" if args.brave_automation_profile else "browser_profile",
    )
    proxy_configs = build_proxy_configs(
        proxy_list_path=resolve_optional_path(project_root, args.proxy_list),
        proxy_server=args.proxy_server,
        proxy_username=args.proxy_username,
        proxy_password=args.proxy_password,
    )
    storage = create_default_storage(project_root, args.output_dir, args.input_partial)

    if args.graphql_cdp_parallel_proxies:
        parallel_browser_path = (
            Path(browser_executable_path) if browser_executable_path else find_brave_executable()
        )
        if parallel_browser_path is None:
            raise SystemExit(
                "Brave Browser was not found. Install Brave or pass --browser-executable-path."
            )
        input_partial_path = resolve_input_partial_path(project_root, args.input_partial)
        profile_root = resolve_parallel_profile_root(project_root, args.parallel_profile_root)
        parallel_options = ParallelCDPOptions(
            browser_executable_path=parallel_browser_path,
            proxy_configs=proxy_configs,
            project_root=project_root,
            input_partial_path=input_partial_path,
            output_root=resolve_output_dir(project_root, args.parallel_output_root),
            profile_root=profile_root,
            start_url=args.start_url,
            worker_count=args.parallel_workers,
            base_port=args.parallel_base_port,
            max_restaurants_total=args.max_restaurants,
            graphql_review_size=args.graphql_review_size,
            detail_delay_min_seconds=args.detail_delay_min_seconds,
            detail_delay_max_seconds=args.detail_delay_max_seconds,
            partial_every_restaurants=args.partial_every_restaurants,
            max_consecutive_detail_failures=args.max_consecutive_detail_failures,
            log_level=args.log_level,
            distributed_slot_count=args.distributed_slot_count,
            distributed_slot_start=args.distributed_slot_start,
            wait_for_manual_ready=not args.parallel_no_manual_wait,
            prepare_only=args.parallel_prepare_only,
            dry_run=args.parallel_dry_run,
            auto_merge=not args.parallel_no_auto_merge,
        )
        raise SystemExit(run_parallel_graphql_cdp(parallel_options))

    if args.calibrate_detail_blocks:
        calibration_options = CalibrationOptions(
            output_dir=resolve_output_dir(project_root, args.calibration_output_dir),
            browser_channel=args.browser_channel,
            browser_executable_path=browser_executable_path,
            headless=headless,
            delay_values=parse_delay_values(
                args.calibration_delay_seconds, args.detail_delay_seconds
            ),
            max_records=args.calibration_max_records,
            batch_size=args.calibration_batch_size,
            max_consecutive_failures=args.max_consecutive_detail_failures,
            proxy_configs=proxy_configs,
            max_proxies=args.calibration_max_proxies,
            time_budget_hours=args.calibration_time_budget_hours,
            cooldown_seconds=args.cooldown_seconds,
            user_data_dir=user_data_dir,
            browser_warmup_url=browser_warmup_url,
            browser_warmup_seconds=browser_warmup_seconds,
            connect_over_cdp_url=args.connect_over_cdp_url,
        )
        run_detail_block_calibration(storage, calibration_options)
        return

    if args.graphql_detail_from_cdp:
        if not args.connect_over_cdp_url:
            raise SystemExit("--graphql-detail-from-cdp requires --connect-over-cdp-url.")
        graphql_options = GraphQLDetailOptions(
            connect_over_cdp_url=args.connect_over_cdp_url,
            max_records=args.max_restaurants,
            review_size=args.graphql_review_size,
            delay_min_seconds=args.detail_delay_min_seconds,
            delay_max_seconds=args.detail_delay_max_seconds,
            partial_every_records=args.partial_every_restaurants,
            max_consecutive_failures=args.max_consecutive_detail_failures,
            detail_shard_count=args.detail_shard_count,
            detail_shard_index=args.detail_shard_index,
        )
        run_graphql_detail_enrichment(storage, graphql_options)
        return

    scraper = TheForkScraper(
        storage=storage,
        start_url=args.start_url,
        browser_channel=args.browser_channel,
        browser_executable_path=browser_executable_path,
        headless=headless,
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
        proxy_403_cooldown_seconds=args.proxy_403_cooldown_seconds,
        pool_403_threshold=args.pool_403_threshold,
        pool_403_window_seconds=args.pool_403_window_seconds,
        pool_403_cooldown_seconds=args.pool_403_cooldown_seconds,
        stop_on_pool_block=args.stop_on_pool_block,
        proxy_max_failed_turns=args.proxy_max_failed_turns,
        proxy_turn_jitter_seconds=args.proxy_turn_jitter_seconds,
        max_url_failures_before_deferral=args.max_url_failures_before_deferral,
        deferred_url_retry_cycles=args.deferred_url_retry_cycles,
        browser_warmup_url=browser_warmup_url,
        browser_warmup_seconds=browser_warmup_seconds,
        max_reviews_per_restaurant=args.max_reviews_per_restaurant,
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


def resolve_input_partial_path(project_root: Path, raw_path: str | None) -> Path:
    if raw_path:
        path = Path(raw_path)
        return path if path.is_absolute() else project_root / path
    return project_root / "data/raw/thefork" / "thefork_milan_restaurants_normalized_partial.json"


def resolve_parallel_profile_root(project_root: Path, raw_path: str | None) -> Path:
    if raw_path:
        path = Path(raw_path)
        return path if path.is_absolute() else project_root / path
    return default_parallel_profile_root(project_root)


def resolve_browser_executable_path(
    raw_path: str | None, use_brave_automation_profile: bool
) -> str | None:
    if raw_path:
        return raw_path
    if not use_brave_automation_profile:
        return None

    detected_path = find_brave_executable()
    if detected_path is None:
        raise SystemExit(
            "Brave Browser was not found. Install Brave or pass "
            "--browser-executable-path with the Brave executable."
        )
    logging.info("Using Brave executable for automation profile: %s", detected_path)
    return str(detected_path)


def find_brave_executable() -> Path | None:
    command_path = (
        shutil.which("brave.exe") or shutil.which("brave") or shutil.which("brave-browser")
    )
    if command_path:
        return Path(command_path)

    candidates = [
        Path(os.environ.get("PROGRAMFILES", ""))
        / "BraveSoftware"
        / "Brave-Browser"
        / "Application"
        / "brave.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "BraveSoftware"
        / "Brave-Browser"
        / "Application"
        / "brave.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "BraveSoftware"
        / "Brave-Browser"
        / "Application"
        / "brave.exe",
        Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        Path("/usr/bin/brave-browser"),
        Path("/usr/bin/brave"),
        Path("/snap/bin/brave"),
    ]
    for candidate in candidates:
        if str(candidate) and candidate.exists():
            return candidate
    return None


def resolve_user_data_dir(
    project_root: Path,
    raw_user_data_dir: str | None,
    use_default: bool,
    default_dir_name: str = "browser_profile",
) -> Path | None:
    if raw_user_data_dir is None:
        if not use_default:
            return None
        if default_dir_name == "brave_automation_profile":
            return default_brave_profile_dir(project_root)
        return project_root / "data/raw/thefork" / default_dir_name
    user_data_dir = Path(raw_user_data_dir)
    if user_data_dir.is_absolute():
        return user_data_dir
    return project_root / user_data_dir


def default_brave_profile_dir(project_root: Path) -> Path:
    if os.name == "nt":
        return Path("C:/tmp/thefork_brave_automation_profile")
    return project_root / "data/raw/thefork" / "brave_automation_profile"


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
