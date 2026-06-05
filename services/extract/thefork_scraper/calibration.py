from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from .detail_scraper import TheForkDetailScraper
from .models import RestaurantRecord
from .proxy_utils import ProxyConfig
from .scraper import (
    DEFAULT_BROWSER_CHANNELS,
    DEFAULT_USER_AGENT,
    START_URL,
    normalize_browser_channel,
)
from .storage import JsonStorage


@dataclass(slots=True)
class CalibrationOptions:
    output_dir: Path
    browser_channel: str | None
    browser_executable_path: str | None
    headless: bool
    delay_values: list[float]
    max_records: int
    batch_size: int
    max_consecutive_failures: int
    proxy_configs: list[ProxyConfig]
    max_proxies: int
    time_budget_hours: float
    cooldown_seconds: int = 900
    user_data_dir: Path | None = None
    navigation_timeout_ms: int = 60_000
    detail_timeout_ms: int = 30_000
    browser_warmup_url: str | None = None
    browser_warmup_seconds: float = 0.0
    connect_over_cdp_url: str | None = None


def run_detail_block_calibration(
    storage: JsonStorage, options: CalibrationOptions
) -> dict[str, Any]:
    options.output_dir.mkdir(parents=True, exist_ok=True)
    records = load_source_records(storage)
    pending_records = [
        record for record in records if record.restaurant_url and not record.detail_scraped
    ]
    completed_count = sum(1 for record in records if record.detail_scraped)

    report: dict[str, Any] = {
        "source": "thefork",
        "created_at": utc_now(),
        "goal": "measure detail-page blocking limits and estimate proxy strategy",
        "limits": {
            "max_proxies": options.max_proxies,
            "time_budget_hours": options.time_budget_hours,
            "cooldown_seconds": options.cooldown_seconds,
        },
        "input_state": {
            "total_records": len(records),
            "detail_completed": completed_count,
            "detail_missing": len(pending_records),
            "partial_path": str(storage.partial_path),
            "final_path": str(storage.final_path),
        },
        "proxy_state": {
            "configured_proxy_count": len(options.proxy_configs),
            "proxy_tests_status": "configured"
            if options.proxy_configs
            else "not_run_no_proxy_list",
            "configured_proxy_labels": [proxy.safe_label() for proxy in options.proxy_configs],
            "user_data_dir": str(options.user_data_dir) if options.user_data_dir else None,
        },
        "test_plan": {
            "max_records_per_run": options.max_records,
            "batch_size": options.batch_size,
            "delay_values_seconds": options.delay_values,
            "max_consecutive_failures": options.max_consecutive_failures,
            "browser_warmup_url": options.browser_warmup_url,
            "browser_warmup_seconds": options.browser_warmup_seconds,
            "connect_over_cdp_url": options.connect_over_cdp_url,
        },
        "test_runs": [],
        "sample_record_files": [],
        "estimates": [],
        "recommended_strategy": {},
        "notes": [],
    }

    if completed_count and pending_records:
        report["notes"].append(
            "The current partial already contains completed detail records and remaining "
            "records, so it is evidence of an earlier block or interruption."
        )

    if options.max_records <= 0:
        report["notes"].append("Live calibration was skipped because max_records is 0.")
    elif not pending_records:
        report["notes"].append("No missing detail records were available for calibration.")
    else:
        selected_records = pending_records[: options.max_records]
        for delay_seconds in options.delay_values:
            record_offset = 0
            for proxy in build_proxy_test_sequence(options.proxy_configs, options.max_proxies):
                records_for_run = selected_records[
                    record_offset : record_offset + options.batch_size
                ]
                record_offset += options.batch_size
                if not records_for_run:
                    break
                run_result, sample_records = run_single_detail_calibration(
                    selected_records=records_for_run,
                    options=options,
                    delay_seconds=delay_seconds,
                    proxy=proxy,
                )
                report["test_runs"].append(run_result)
                sample_file = save_sample_records(options.output_dir, run_result, sample_records)
                if sample_file is not None:
                    report["sample_record_files"].append(str(sample_file))

    historical_test_runs = load_historical_test_runs(options.output_dir, "thefork")
    combined_test_runs = [*historical_test_runs, *report["test_runs"]]
    report["historical_test_runs_loaded"] = len(historical_test_runs)
    report["estimates"] = estimate_proxy_completion(
        pending_count=len(pending_records),
        delay_values=options.delay_values,
        test_runs=combined_test_runs,
        max_proxies=options.max_proxies,
        time_budget_hours=options.time_budget_hours,
        cooldown_seconds=options.cooldown_seconds,
    )
    report["recommended_strategy"] = choose_recommended_strategy(report, combined_test_runs)
    save_report(options.output_dir / "thefork_block_calibration_report.json", report)
    return report


def load_source_records(storage: JsonStorage) -> list[RestaurantRecord]:
    partial_records = storage.load_partial()
    if partial_records:
        return partial_records
    if storage.final_path.exists():
        with storage.final_path.open("r", encoding="utf-8") as input_file:
            payload = json.load(input_file)
        return [RestaurantRecord(**item) for item in payload]
    return []


def build_proxy_test_sequence(
    proxy_configs: list[ProxyConfig], max_proxies: int
) -> list[ProxyConfig | None]:
    if not proxy_configs:
        return [None]
    return list(proxy_configs[: max(0, max_proxies)])


def run_single_detail_calibration(
    selected_records: list[RestaurantRecord],
    options: CalibrationOptions,
    delay_seconds: float,
    proxy: ProxyConfig | None,
) -> tuple[dict[str, Any], list[RestaurantRecord]]:
    started_at = utc_now()
    started_monotonic = time.monotonic()
    sample_records = [RestaurantRecord(**record.to_dict()) for record in selected_records]
    result: dict[str, Any] = {
        "run_id": build_run_id(delay_seconds, proxy),
        "started_at": started_at,
        "browser_channel": options.browser_channel or "auto",
        "proxy_label": proxy.safe_label() if proxy else "direct_ip",
        "proxy_used": proxy is not None,
        "delay_seconds": delay_seconds,
        "attempted": 0,
        "succeeded": 0,
        "failed": 0,
        "first_failure_attempt": None,
        "stopped_by_consecutive_failures": False,
        "duration_seconds": 0.0,
        "average_seconds_per_success": None,
        "error": None,
    }

    if not sample_records:
        result["error"] = "No sample records were available."
        return result, sample_records

    try:
        run_detail_attempts(sample_records, options, delay_seconds, proxy, result)
    except Exception as error:  # noqa: BLE001 - calibration must always save a report.
        result["error"] = str(error)
        logging.warning("TheFork calibration run failed: %s", error)

    result["duration_seconds"] = round(time.monotonic() - started_monotonic, 3)
    if result["succeeded"]:
        result["average_seconds_per_success"] = round(
            result["duration_seconds"] / result["succeeded"], 3
        )
    return result, sample_records


def run_detail_attempts(
    sample_records: list[RestaurantRecord],
    options: CalibrationOptions,
    delay_seconds: float,
    proxy: ProxyConfig | None,
    result: dict[str, Any],
) -> None:
    detail_scraper = TheForkDetailScraper(
        navigation_timeout_ms=options.navigation_timeout_ms,
        detail_timeout_ms=options.detail_timeout_ms,
    )
    if options.connect_over_cdp_url:
        run_detail_attempts_with_existing_browser(
            detail_scraper,
            sample_records,
            options,
            delay_seconds,
            proxy,
            result,
        )
        return

    if options.browser_executable_path:
        channels = [None]
    elif options.browser_channel:
        channels = [normalize_browser_channel(options.browser_channel)]
    else:
        channels = list(DEFAULT_BROWSER_CHANNELS)
    last_error: Exception | None = None

    for channel in channels:
        try:
            with sync_playwright() as playwright:
                launch_options: dict[str, Any] = {
                    "headless": options.headless,
                    "chromium_sandbox": True,
                    "args": []
                    if options.browser_executable_path
                    else ["--disable-blink-features=AutomationControlled"],
                }
                if options.browser_executable_path:
                    launch_options["executable_path"] = options.browser_executable_path
                elif channel is not None:
                    launch_options["channel"] = channel
                if proxy is not None:
                    launch_options["proxy"] = proxy.to_playwright()

                context_options: dict[str, Any] = {
                    "locale": "it-IT",
                    "timezone_id": "Europe/Rome",
                    "viewport": {"width": 1440, "height": 1800},
                    "user_agent": DEFAULT_USER_AGENT,
                    "extra_http_headers": {
                        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
                    },
                }
                browser = None
                if options.user_data_dir is not None:
                    profile_dir = profile_dir_for_proxy(options.user_data_dir, proxy)
                    profile_dir.mkdir(parents=True, exist_ok=True)
                    logging.info("Using TheFork calibration profile: %s", profile_dir)
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(profile_dir),
                        **launch_options,
                        **context_options,
                    )
                else:
                    browser = playwright.chromium.launch(**launch_options)
                    context = browser.new_context(**context_options)
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(options.detail_timeout_ms)
                page.set_default_navigation_timeout(options.navigation_timeout_ms)
                try:
                    warm_up_browser_profile(page, options)
                    execute_record_attempts(
                        detail_scraper, page, sample_records, delay_seconds, options, result
                    )
                    result["browser_channel"] = channel or "bundled chromium"
                    return
                finally:
                    context.close()
                    if browser is not None:
                        browser.close()
        except PlaywrightError as error:
            last_error = error
            logging.warning(
                "Could not run calibration with channel %s: %s",
                channel or "bundled chromium",
                error,
            )

    if last_error is not None:
        raise RuntimeError(
            f"No browser channel could run the calibration: {last_error}"
        ) from last_error


def run_detail_attempts_with_existing_browser(
    detail_scraper: TheForkDetailScraper,
    sample_records: list[RestaurantRecord],
    options: CalibrationOptions,
    delay_seconds: float,
    proxy: ProxyConfig | None,
    result: dict[str, Any],
) -> None:
    if proxy is not None:
        logging.warning(
            "Ignoring proxy %s because --connect-over-cdp-url uses the already-open "
            "browser network.",
            proxy.safe_label(),
        )

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(options.connect_over_cdp_url)
        except PlaywrightError as error:
            raise RuntimeError(
                f"Could not connect to existing browser at {options.connect_over_cdp_url}: {error}"
            ) from error

        if not browser.contexts:
            raise RuntimeError("The connected browser has no available browser context.")

        context = browser.contexts[0]
        page = context.new_page()
        page.set_default_timeout(options.detail_timeout_ms)
        page.set_default_navigation_timeout(options.navigation_timeout_ms)
        try:
            warm_up_browser_profile(page, options)
            execute_record_attempts(
                detail_scraper, page, sample_records, delay_seconds, options, result
            )
            result["browser_channel"] = "connected_cdp"
        finally:
            try:
                page.close()
            except PlaywrightError:
                pass


def warm_up_browser_profile(page: Any, options: CalibrationOptions) -> None:
    warmup_url = options.browser_warmup_url
    warmup_seconds = max(0.0, options.browser_warmup_seconds)
    if not warmup_url and warmup_seconds <= 0:
        return

    target_url = warmup_url or START_URL
    logging.info("Warming up browser profile on %s for %.1f seconds.", target_url, warmup_seconds)
    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=options.navigation_timeout_ms)
        page.wait_for_timeout(2500)
        page.mouse.wheel(0, 420)
        page.wait_for_timeout(1200)
        page.mouse.wheel(0, 360)
        if warmup_seconds > 0:
            page.wait_for_timeout(int(warmup_seconds * 1000))
    except PlaywrightError as error:
        logging.warning("Browser warm-up failed, continuing with detail calibration: %s", error)


def execute_record_attempts(
    detail_scraper: TheForkDetailScraper,
    page: Any,
    sample_records: list[RestaurantRecord],
    delay_seconds: float,
    options: CalibrationOptions,
    result: dict[str, Any],
) -> None:
    consecutive_failures = 0
    scraped_at = utc_now()
    for index, record in enumerate(sample_records, start=1):
        logging.info(
            "TheFork calibration %s: detail attempt %s/%s",
            result["run_id"],
            index,
            len(sample_records),
        )
        enriched_record = detail_scraper.enrich_record(page, record, scraped_at)
        sample_records[index - 1] = enriched_record
        result["attempted"] += 1

        if enriched_record.detail_scraped:
            result["succeeded"] += 1
            consecutive_failures = 0
        else:
            result["failed"] += 1
            consecutive_failures += 1
            if result["first_failure_attempt"] is None:
                result["first_failure_attempt"] = index

        if consecutive_failures >= options.max_consecutive_failures:
            result["stopped_by_consecutive_failures"] = True
            break

        if delay_seconds > 0 and index < len(sample_records):
            time.sleep(delay_seconds)


def estimate_proxy_completion(
    pending_count: int,
    delay_values: list[float],
    test_runs: list[dict[str, Any]],
    max_proxies: int,
    time_budget_hours: float,
    cooldown_seconds: int,
) -> list[dict[str, Any]]:
    best_run = best_successful_run(test_runs)
    fallback_seconds = max(delay_values or [2.0]) + 20.0
    seconds_per_detail = (
        float(best_run["average_seconds_per_success"])
        if best_run and best_run.get("average_seconds_per_success")
        else fallback_seconds
    )
    success_rate = (
        best_run["succeeded"] / best_run["attempted"]
        if best_run and best_run.get("attempted")
        else None
    )
    safe_batch_size = observed_safe_batch_size(best_run)

    estimates: list[dict[str, Any]] = []
    for proxy_count in range(1, max(1, max_proxies) + 1):
        records_per_proxy = pending_count / proxy_count
        work_seconds = records_per_proxy * seconds_per_detail
        cooldown_cycles = (
            max(0, int((records_per_proxy - 1) // safe_batch_size)) if safe_batch_size else 0
        )
        cooldown_penalty_seconds = cooldown_cycles * cooldown_seconds
        estimated_hours = (work_seconds + cooldown_penalty_seconds) / 3600
        estimates.append(
            {
                "proxy_count": proxy_count,
                "estimated_hours": round(estimated_hours, 2),
                "fits_time_budget": estimated_hours <= time_budget_hours,
                "seconds_per_detail_used": round(seconds_per_detail, 3),
                "safe_batch_size_used": safe_batch_size,
                "cooldown_cycles_per_proxy": cooldown_cycles,
                "cooldown_penalty_hours_per_proxy": round(cooldown_penalty_seconds / 3600, 2),
                "success_rate_source": round(success_rate, 3) if success_rate is not None else None,
                "evidence": "live_calibration" if best_run else "fallback_estimate",
            }
        )
    return estimates


def choose_recommended_strategy(
    report: dict[str, Any], test_runs: list[dict[str, Any]]
) -> dict[str, Any]:
    feasible = [estimate for estimate in report["estimates"] if estimate["fits_time_budget"]]
    minimum_proxy_count = feasible[0]["proxy_count"] if feasible else None
    margin_target_hours = report["limits"]["time_budget_hours"] * 0.75
    margin_feasible = [
        estimate
        for estimate in report["estimates"]
        if estimate["estimated_hours"] <= margin_target_hours
    ]
    recommended_proxy_count = (
        margin_feasible[0]["proxy_count"] if margin_feasible else minimum_proxy_count
    )
    safe_batch_size = (
        report["estimates"][0].get("safe_batch_size_used")
        if report["estimates"]
        else report["test_plan"]["batch_size"]
    )
    best_run = best_successful_run(test_runs)
    delay_seconds = (
        best_run["delay_seconds"]
        if best_run
        else max(report["test_plan"]["delay_values_seconds"] or [10.0])
    )

    return {
        "minimum_proxy_count_for_time_budget": minimum_proxy_count,
        "recommended_proxy_count_with_margin": recommended_proxy_count,
        "margin_target_hours": round(margin_target_hours, 2),
        "recommended_delay_seconds": delay_seconds,
        "recommended_batch_size": safe_batch_size,
        "rotation_mode": "alternating_batches",
        "parallelism_mode": "staggered_parallel_only_after_each_proxy_passes_calibration",
        "why": (
            "Use one browser session per proxy, rotate proxies between batches, and start "
            "parallel workers only after each proxy completes a small calibration batch "
            "without blocks."
        ),
        "proxy_gap": (
            "No real proxy list was supplied, so direct-IP data and estimates are saved "
            "but proxy validation is still pending."
            if report["proxy_state"]["configured_proxy_count"] == 0
            else None
        ),
    }


def best_successful_run(test_runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    successful_runs = [run for run in test_runs if run.get("succeeded") and not run.get("error")]
    if not successful_runs:
        return None
    return max(
        successful_runs,
        key=lambda run: (
            observed_safe_batch_size(run),
            -float(run.get("average_seconds_per_success") or 999999),
        ),
    )


def load_historical_test_runs(output_dir: Path, source: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for report_path in sorted(output_dir.glob(f"{source}_block_calibration_report_*.json")):
        try:
            with report_path.open("r", encoding="utf-8") as input_file:
                payload = json.load(input_file)
        except (OSError, json.JSONDecodeError):
            continue
        for run in payload.get("test_runs", []):
            if isinstance(run, dict):
                runs.append(run)
    return runs


def observed_safe_batch_size(run: dict[str, Any] | None) -> int:
    if not run:
        return 20
    first_failure_attempt = run.get("first_failure_attempt")
    if isinstance(first_failure_attempt, int) and first_failure_attempt > 1:
        return first_failure_attempt - 1
    succeeded = int(run.get("succeeded") or 0)
    attempted = int(run.get("attempted") or 0)
    if attempted and succeeded == attempted:
        return max(1, attempted)
    return max(1, succeeded)


def profile_dir_for_proxy(base_dir: Path, proxy: ProxyConfig | None) -> Path:
    if proxy is None:
        return base_dir
    return base_dir.parent / "browser_profiles" / proxy.safe_label()


def save_sample_records(
    output_dir: Path, run_result: dict[str, Any], records: list[RestaurantRecord]
) -> Path | None:
    if not records:
        return None
    path = output_dir / f"{run_result['run_id']}_records.json"
    if path.exists():
        path = output_dir / f"{run_result['run_id']}_{file_timestamp()}_records.json"
    with path.open("w", encoding="utf-8") as output_file:
        json.dump(
            [record.to_dict() for record in records], output_file, ensure_ascii=False, indent=2
        )
        output_file.write("\n")
    return path


def save_report(path: Path, report: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as output_file:
        json.dump(report, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    archive_path = path.with_name(f"{path.stem}_{file_timestamp()}{path.suffix}")
    with archive_path.open("w", encoding="utf-8") as output_file:
        json.dump(report, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    logging.info("Saved TheFork calibration report to %s", path)


def build_run_id(delay_seconds: float, proxy: ProxyConfig | None) -> str:
    delay_label = str(delay_seconds).replace(".", "_")
    proxy_label = proxy.safe_label() if proxy else "direct_ip"
    return f"thefork_delay_{delay_label}_{proxy_label}"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
