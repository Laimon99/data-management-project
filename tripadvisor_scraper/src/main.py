from __future__ import annotations

import argparse
import logging
import os
import shutil
from pathlib import Path

from . import config
from .calibration import CalibrationOptions, run_detail_block_calibration
from .cdp_detail import CDPDetailOptions, run_cdp_detail_enrichment
from .cdp_parallel import ParallelCDPOptions, default_parallel_profile_root, run_parallel_cdp
from .proxy_utils import build_proxy_configs
from .scraper import START_URL, TripadvisorScraper, create_default_storage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Tripadvisor Milan listing pages into normalized JSON.")
    parser.add_argument("--start-url", default=START_URL, help="Tripadvisor Milan listing URL to start from.")
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
    parser.add_argument(
        "--brave-automation-profile",
        action="store_true",
        help="Use Brave Browser with a headed persistent automation profile.",
    )
    parser.add_argument(
        "--browser-warmup-url",
        default=None,
        help="Optional URL to open before scraping to warm up a persistent browser profile.",
    )
    parser.add_argument(
        "--browser-warmup-seconds",
        type=float,
        default=None,
        help="Seconds to wait on the warm-up URL before scraping.",
    )
    parser.add_argument(
        "--connect-over-cdp-url",
        default=None,
        help="Connect to an already-open Chromium/Brave instance, for example http://127.0.0.1:9222.",
    )
    parser.add_argument(
        "--cdp-detail-from-browser",
        action="store_true",
        help="Enrich missing detail pages through an already-open Brave/Chromium tab connected over CDP.",
    )
    parser.add_argument(
        "--cdp-parallel-proxies",
        action="store_true",
        help="Launch multiple Brave proxy profiles and run parallel CDP detail workers.",
    )
    parser.add_argument(
        "--parallel-workers",
        type=int,
        default=2,
        help="Number of Brave proxy profiles / CDP workers to run in --cdp-parallel-proxies mode.",
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
        help="Directory for parallel Brave user data dirs. Defaults to C:/tmp/tripadvisor_cdp_proxy_profiles on Windows.",
    )
    parser.add_argument(
        "--parallel-output-root",
        default="output/runs/cdp_parallel",
        help="Base output directory for parallel CDP runs. Each execution creates a fresh run_YYYYMMDD_HHMMSS child.",
    )
    parser.add_argument(
        "--parallel-prepare-only",
        action="store_true",
        help="Launch the Brave proxy profiles and print worker commands, but do not start scraping workers.",
    )
    parser.add_argument(
        "--parallel-dry-run",
        action="store_true",
        help="Print the parallel plan without launching browsers or workers.",
    )
    parser.add_argument(
        "--parallel-no-manual-wait",
        action="store_true",
        help="Start workers immediately after CDP ports are ready instead of waiting for manual Tripadvisor checks.",
    )
    parser.add_argument(
        "--parallel-no-auto-merge",
        action="store_true",
        help="Do not merge worker partial files back into the input partial after parallel workers finish.",
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
        "--proxy-round-robin",
        action="store_true",
        help="Rotate proxies after a small number of detail pages and rest each proxy before reuse.",
    )
    parser.add_argument(
        "--include-direct-ip-after-proxies",
        action="store_true",
        help="After all proxies are retired, continue round-robin mode with the direct IP.",
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
    parser.add_argument("--proxy-list", default=None, help="Path to a text file with one proxy URL per line.")
    parser.add_argument("--proxy-server", default=None, help="Single proxy server, for example http://host:port.")
    parser.add_argument("--proxy-username", default=None, help="Username for --proxy-server.")
    parser.add_argument("--proxy-password", default=None, help="Password for --proxy-server.")
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
        help="Comma-separated detail delays to test, for example 10,20,30.",
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
    if args.distributed_slot_count is not None and args.distributed_slot_count < 1:
        raise SystemExit("--distributed-slot-count must be at least 1.")
    if args.distributed_slot_start < 0:
        raise SystemExit("--distributed-slot-start must be zero or greater.")

    project_root = Path(__file__).resolve().parents[1]
    if args.save_session_only and not args.manual_unlock:
        logging.info("Enabling manual unlock mode because --save-session-only was requested.")
        args.manual_unlock = True

    browser_executable_path = resolve_browser_executable_path(
        args.browser_executable_path,
        args.brave_automation_profile,
    )
    headless = not (args.headed or args.brave_automation_profile)
    browser_warmup_url = args.browser_warmup_url or (args.start_url if args.brave_automation_profile else None)
    browser_warmup_seconds = (
        args.browser_warmup_seconds
        if args.browser_warmup_seconds is not None
        else (30.0 if args.brave_automation_profile else 0.0)
    )
    user_data_dir = resolve_user_data_dir(
        project_root,
        args.user_data_dir,
        args.manual_unlock
        or args.auto_detail_until_complete
        or args.proxy_round_robin
        or bool(args.proxy_list or args.proxy_server)
        or args.brave_automation_profile,
        "brave_automation_profile" if args.brave_automation_profile else "browser_profile",
    )
    proxy_configs = build_proxy_configs(
        proxy_list_path=resolve_optional_path(project_root, args.proxy_list),
        proxy_server=args.proxy_server,
        proxy_username=args.proxy_username,
        proxy_password=args.proxy_password,
    )
    storage = create_default_storage(project_root, args.output_dir, args.input_partial)

    if args.cdp_parallel_proxies:
        parallel_browser_path = Path(browser_executable_path) if browser_executable_path else find_brave_executable()
        if parallel_browser_path is None:
            raise SystemExit("Brave Browser was not found. Install Brave or pass --browser-executable-path.")
        input_partial_path = resolve_input_partial_path(project_root, args.input_partial)
        if not args.parallel_dry_run:
            input_partial_path = ensure_input_partial_available(project_root, input_partial_path, args.input_partial)
        parallel_options = ParallelCDPOptions(
            browser_executable_path=parallel_browser_path,
            proxy_configs=proxy_configs,
            project_root=project_root,
            input_partial_path=input_partial_path,
            output_root=resolve_output_dir(project_root, args.parallel_output_root),
            profile_root=resolve_parallel_profile_root(project_root, args.parallel_profile_root),
            start_url=args.start_url,
            worker_count=args.parallel_workers,
            base_port=args.parallel_base_port,
            max_restaurants_total=args.max_restaurants,
            detail_delay_min_seconds=coalesce_delay(args.detail_delay_min_seconds, args.detail_delay_seconds),
            detail_delay_max_seconds=coalesce_delay(args.detail_delay_max_seconds, args.detail_delay_seconds),
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
        raise SystemExit(run_parallel_cdp(parallel_options))

    if args.calibrate_detail_blocks:
        calibration_options = CalibrationOptions(
            output_dir=resolve_output_dir(project_root, args.calibration_output_dir),
            browser_channel=args.browser_channel,
            headless=headless,
            delay_values=parse_delay_values(args.calibration_delay_seconds, args.detail_delay_seconds),
            max_records=args.calibration_max_records,
            batch_size=args.calibration_batch_size,
            max_consecutive_failures=args.max_consecutive_detail_failures,
            proxy_configs=proxy_configs,
            max_proxies=args.calibration_max_proxies,
            time_budget_hours=args.calibration_time_budget_hours,
            cooldown_seconds=args.cooldown_seconds,
            user_data_dir=user_data_dir,
            manual_unlock=args.manual_unlock,
            unlock_timeout_seconds=args.unlock_timeout_seconds,
        )
        run_detail_block_calibration(storage, calibration_options)
        return

    if args.cdp_detail_from_browser:
        if not args.connect_over_cdp_url:
            raise SystemExit("--cdp-detail-from-browser requires --connect-over-cdp-url.")
        cdp_options = CDPDetailOptions(
            connect_over_cdp_url=args.connect_over_cdp_url,
            max_records=args.max_restaurants,
            delay_min_seconds=args.detail_delay_min_seconds,
            delay_max_seconds=args.detail_delay_max_seconds,
            partial_every_records=args.partial_every_restaurants,
            max_consecutive_failures=args.max_consecutive_detail_failures,
            detail_shard_count=args.detail_shard_count,
            detail_shard_index=args.detail_shard_index,
            human_scroll_enabled=args.human_detail_scroll,
        )
        run_cdp_detail_enrichment(storage, cdp_options)
        return

    scraper = TripadvisorScraper(
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
        partial_every_pages=args.partial_every_pages,
        partial_every_restaurants=args.partial_every_restaurants,
        scrape_detail_pages=not args.no_detail_pages,
        user_data_dir=user_data_dir,
        manual_unlock=args.manual_unlock,
        unlock_timeout_seconds=args.unlock_timeout_seconds,
        save_session_only=args.save_session_only,
        resume=args.resume,
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
        proxy_round_robin=args.proxy_round_robin,
        include_direct_ip_after_proxies=args.include_direct_ip_after_proxies,
        restaurants_per_proxy_turn=args.restaurants_per_proxy_turn,
        proxy_min_rest_seconds=args.proxy_min_rest_seconds,
        proxy_max_failed_turns=args.proxy_max_failed_turns,
        proxy_turn_jitter_seconds=args.proxy_turn_jitter_seconds,
        browser_warmup_url=browser_warmup_url,
        browser_warmup_seconds=browser_warmup_seconds,
    )

    try:
        records = scraper.scrape(max_pages=args.max_pages, max_restaurants=args.max_restaurants)
    except RuntimeError as error:
        logging.error("%s", error)
        raise SystemExit(1)

    logging.info("Scraping completed with %s normalized restaurant records.", len(records))


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
        return project_root / "output" / default_dir_name

    user_data_dir = Path(raw_user_data_dir)
    if user_data_dir.is_absolute():
        return user_data_dir
    return project_root / user_data_dir


def default_brave_profile_dir(project_root: Path) -> Path:
    if os.name == "nt":
        return Path("C:/tmp/tripadvisor_brave_automation_profile")
    return project_root / "output" / "brave_automation_profile"


def resolve_input_partial_path(project_root: Path, raw_path: str | None) -> Path:
    if raw_path:
        path = Path(raw_path)
        return path if path.is_absolute() else project_root / path
    return project_root / "output" / "tripadvisor_milan_restaurants_normalized_partial.json"


def ensure_input_partial_available(project_root: Path, input_partial_path: Path, raw_path: str | None) -> Path:
    if input_partial_path.exists():
        return input_partial_path
    if raw_path:
        raise SystemExit(f"Input partial not found: {input_partial_path}")

    legacy_normalized_path = project_root / "output" / "tripadvisor_milan_restaurants_normalized.json"
    if not legacy_normalized_path.exists():
        raise SystemExit(
            "No partial JSON was found. Run listing scraping first or pass --input-partial."
        )

    input_partial_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy_normalized_path, input_partial_path)
    logging.info("Created base partial from existing listing dataset: %s", input_partial_path)
    return input_partial_path


def resolve_parallel_profile_root(project_root: Path, raw_path: str | None) -> Path:
    if raw_path:
        path = Path(raw_path)
        return path if path.is_absolute() else project_root / path
    return default_parallel_profile_root(project_root)


def resolve_browser_executable_path(raw_path: str | None, use_brave_automation_profile: bool) -> str | None:
    if raw_path:
        return raw_path
    if not use_brave_automation_profile:
        return None

    detected_path = find_brave_executable()
    if detected_path is None:
        raise SystemExit(
            "Brave Browser was not found. Install Brave or pass --browser-executable-path with the Brave executable."
        )
    logging.info("Using Brave executable for automation profile: %s", detected_path)
    return str(detected_path)


def find_brave_executable() -> Path | None:
    command_path = shutil.which("brave.exe") or shutil.which("brave") or shutil.which("brave-browser")
    if command_path:
        return Path(command_path)

    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        Path("/usr/bin/brave-browser"),
        Path("/usr/bin/brave"),
        Path("/snap/bin/brave"),
    ]
    for candidate in candidates:
        if str(candidate) and candidate.exists():
            return candidate
    return None


def resolve_optional_path(project_root: Path, raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)
    return str(project_root / path)


def resolve_output_dir(project_root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return project_root / path


def coalesce_delay(raw_value: float | None, fallback: float) -> float:
    return fallback if raw_value is None else raw_value


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
