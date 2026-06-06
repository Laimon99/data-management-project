from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from .merge_outputs import build_stats, choose_record, load_records, merge_key, summarize_sources, write_json
from .proxy_utils import ProxyConfig


@dataclass(frozen=True, slots=True)
class ParallelCDPOptions:
    browser_executable_path: Path
    proxy_configs: list[ProxyConfig]
    project_root: Path
    input_partial_path: Path
    output_root: Path
    profile_root: Path
    start_url: str
    worker_count: int
    base_port: int
    max_restaurants_total: int | None
    detail_delay_min_seconds: float
    detail_delay_max_seconds: float
    partial_every_restaurants: int
    max_consecutive_detail_failures: int
    max_reviews_per_restaurant: int
    log_level: str
    distributed_slot_count: int | None = None
    distributed_slot_start: int = 0
    wait_for_manual_ready: bool = True
    prepare_only: bool = False
    dry_run: bool = False
    auto_merge: bool = True


def run_parallel_cdp(options: ParallelCDPOptions) -> int:
    run_started_at = time.time()
    options = replace(options, output_root=unique_run_output_root(options.output_root))
    workers = build_worker_specs(options)
    if options.dry_run:
        print_plan(workers, options)
        return 0

    options.output_root.mkdir(parents=True, exist_ok=True)
    options.profile_root.mkdir(parents=True, exist_ok=True)

    for worker in workers:
        launch_brave_worker(worker, options)
        wait_for_cdp(worker["port"])

    print_plan(workers, options)
    if options.prepare_only:
        logging.info("Prepare-only mode finished after launching %s browser profiles.", len(workers))
        return 0

    if options.wait_for_manual_ready:
        input(
            "Open/check Tripadvisor in each Brave window, solve cookies/captcha/proxy prompts if needed, "
            "then press Enter to start CDP detail workers..."
        )

    worker_processes = [subprocess.Popen(worker["command"], cwd=options.project_root) for worker in workers]
    exit_codes = [process.wait() for process in worker_processes]

    merge_failed = False
    merge_report = None
    if options.auto_merge:
        try:
            merge_report = merge_parallel_worker_outputs(workers, options, run_started_at)
        except Exception:
            merge_failed = True
            logging.exception("Automatic merge of parallel worker outputs failed.")
    else:
        logging.info("Automatic merge disabled. Worker partials remain in %s.", options.output_root)

    failed_codes = [code for code in exit_codes if code != 0]
    if failed_codes:
        logging.warning("One or more Tripadvisor CDP workers failed: %s", failed_codes)
        return failed_codes[0]
    if merge_failed:
        return 1

    if merge_report is not None:
        pending_detail = int(merge_report.get("pending_detail") or 0)
        if pending_detail > 0:
            logging.warning("Parallel CDP run finished, but %s records still miss detail data.", pending_detail)
        else:
            logging.info("Parallel CDP run completed and all records have detail data.")
    return 0


def merge_parallel_worker_outputs(workers: list[dict], options: ParallelCDPOptions, run_started_at: float) -> dict:
    input_path = options.input_partial_path
    if not input_path.exists():
        raise FileNotFoundError(f"Input partial not found for automatic merge: {input_path}")

    worker_partial_paths = fresh_worker_partial_paths(workers, run_started_at)
    if not worker_partial_paths:
        logging.warning("No fresh worker partial files found. Leaving input partial unchanged.")
        return write_no_worker_merge_report(input_path)

    backup_path = backup_partial_path(input_path)
    shutil.copy2(input_path, backup_path)

    input_paths = [input_path, *worker_partial_paths]
    merged_by_key: dict[str, dict] = {}
    source_by_key: dict[str, str] = {}
    input_reports = []
    replacement_reasons: dict[str, int] = {}

    for input_file in input_paths:
        records = load_records(input_file)
        input_reports.append(build_stats(input_file, records))
        for record in records:
            key = merge_key(record)
            current = merged_by_key.get(key)
            if current is None:
                merged_by_key[key] = record
                source_by_key[key] = str(input_file)
                continue

            chosen, reason = choose_record(current, record)
            if chosen is record:
                merged_by_key[key] = record
                source_by_key[key] = str(input_file)
                replacement_reasons[reason] = replacement_reasons.get(reason, 0) + 1

    merged_records = list(merged_by_key.values())
    write_json(input_path, merged_records)
    final_output_path, pending_detail, final_output_written = write_final_output_if_complete(input_path, merged_records)

    report_path = input_path.with_suffix(".parallel_merge_report.json")
    output_stats = build_stats(input_path, merged_records)
    output_stats["pending_detail"] = pending_detail
    report = {
        "inputs": input_reports,
        "output": output_stats,
        "pending_detail": pending_detail,
        "replacement_reasons": replacement_reasons,
        "chosen_sources": summarize_sources(source_by_key),
        "backup_path": str(backup_path),
        "worker_partials": [str(path) for path in worker_partial_paths],
        "final_output_path": str(final_output_path),
        "final_output_written": final_output_written,
        "merged_at": timestamp_for_filename(),
    }
    write_json(report_path, report)

    logging.info("Automatic merge wrote %s records to %s.", len(merged_records), input_path)
    if final_output_written:
        logging.info("Complete enriched output written to %s.", final_output_path)
    else:
        logging.warning("Enriched final output not written because %s records still miss detail data.", pending_detail)
    logging.info("Automatic merge backup written to %s.", backup_path)
    logging.info("Automatic merge report written to %s.", report_path)
    return report


def write_no_worker_merge_report(input_path: Path) -> dict:
    records = load_records(input_path)
    final_output_path, pending_detail, final_output_written = write_final_output_if_complete(input_path, records)
    report_path = input_path.with_suffix(".parallel_merge_report.json")
    output_stats = build_stats(input_path, records)
    output_stats["pending_detail"] = pending_detail
    report = {
        "inputs": [build_stats(input_path, records)],
        "output": output_stats,
        "pending_detail": pending_detail,
        "replacement_reasons": {},
        "chosen_sources": {str(input_path): len(records)},
        "backup_path": None,
        "worker_partials": [],
        "merge_skipped_reason": "no_fresh_worker_partials",
        "final_output_path": str(final_output_path),
        "final_output_written": final_output_written,
        "merged_at": timestamp_for_filename(),
    }
    write_json(report_path, report)
    return report


def write_final_output_if_complete(input_path: Path, records: list[dict]) -> tuple[Path, int, bool]:
    final_output_path = input_path.parent / "tripadvisor_milan_restaurants_enriched.json"
    pending_detail = sum(1 for record in records if record.get("detail_scraped") is not True)
    if pending_detail == 0:
        write_json(final_output_path, records)
        return final_output_path, pending_detail, True
    return final_output_path, pending_detail, False


def fresh_worker_partial_paths(workers: list[dict], run_started_at: float) -> list[Path]:
    paths = []
    minimum_mtime = run_started_at - 2.0
    for worker in workers:
        partial_path = worker["output_dir"] / "tripadvisor_milan_restaurants_normalized_partial.json"
        if not partial_path.exists():
            logging.info("Worker %s produced no partial file to merge.", worker["worker_number"])
            continue
        if partial_path.stat().st_mtime < minimum_mtime:
            logging.warning("Skipping stale worker partial from a previous run: %s", partial_path)
            continue
        paths.append(partial_path)
    return paths


def backup_partial_path(input_path: Path) -> Path:
    timestamp = timestamp_for_filename()
    return input_path.with_name(f"{input_path.stem}_before_parallel_merge_{timestamp}{input_path.suffix}")


def timestamp_for_filename() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def build_worker_specs(options: ParallelCDPOptions) -> list[dict]:
    if not options.proxy_configs:
        raise RuntimeError("--cdp-parallel-proxies requires at least one proxy.")
    worker_count = min(max(1, options.worker_count), len(options.proxy_configs))
    shard_count = options.distributed_slot_count or worker_count
    if shard_count < 1:
        raise RuntimeError("--distributed-slot-count must be at least 1.")
    if options.distributed_slot_start < 0:
        raise RuntimeError("--distributed-slot-start must be zero or greater.")
    if options.distributed_slot_count is not None and options.distributed_slot_start + worker_count > shard_count:
        raise RuntimeError(
            "--distributed-slot-start + actual worker count must be <= --distributed-slot-count."
        )
    max_per_worker = None
    if options.max_restaurants_total is not None:
        max_per_worker = max(1, math.ceil(options.max_restaurants_total / worker_count))

    workers = []
    for zero_index, proxy_config in enumerate(options.proxy_configs[:worker_count]):
        worker_number = zero_index + 1
        port = options.base_port + zero_index
        profile_dir = options.profile_root / f"worker_{worker_number:02d}_{proxy_config.safe_label()}"
        extension_dir = profile_dir / "proxy_auth_extension"
        output_dir = options.output_root / f"worker_{worker_number:02d}_{proxy_config.safe_label()}"
        shard_index = options.distributed_slot_start + zero_index + 1
        command = build_worker_command(options, worker_number, shard_count, shard_index, port, output_dir, max_per_worker)
        workers.append(
            {
                "worker_number": worker_number,
                "worker_count": worker_count,
                "shard_count": shard_count,
                "shard_index": shard_index,
                "distributed_slot": shard_index - 1,
                "proxy": proxy_config,
                "port": port,
                "cdp_url": f"http://127.0.0.1:{port}",
                "profile_dir": profile_dir,
                "extension_dir": extension_dir,
                "output_dir": output_dir,
                "command": command,
            }
        )
    return workers


def build_worker_command(
    options: ParallelCDPOptions,
    worker_number: int,
    shard_count: int,
    shard_index: int,
    port: int,
    output_dir: Path,
    max_per_worker: int | None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "src.main",
        "--cdp-detail-from-browser",
        "--connect-over-cdp-url",
        f"http://127.0.0.1:{port}",
        "--input-partial",
        str(options.input_partial_path),
        "--output-dir",
        str(output_dir),
        "--detail-shard-count",
        str(shard_count),
        "--detail-shard-index",
        str(shard_index),
        "--partial-every-restaurants",
        str(options.partial_every_restaurants),
        "--detail-delay-min-seconds",
        str(options.detail_delay_min_seconds),
        "--detail-delay-max-seconds",
        str(options.detail_delay_max_seconds),
        "--max-consecutive-detail-failures",
        str(options.max_consecutive_detail_failures),
        "--max-reviews-per-restaurant",
        str(options.max_reviews_per_restaurant),
        "--human-detail-scroll",
        "--log-level",
        options.log_level,
    ]
    if max_per_worker is not None:
        command.extend(["--max-restaurants", str(max_per_worker)])
    return command


def launch_brave_worker(worker: dict, options: ParallelCDPOptions) -> subprocess.Popen:
    proxy_config: ProxyConfig = worker["proxy"]
    create_proxy_auth_extension(worker["extension_dir"], proxy_config)
    worker["profile_dir"].mkdir(parents=True, exist_ok=True)

    args = [
        str(options.browser_executable_path),
        f"--remote-debugging-port={worker['port']}",
        f"--user-data-dir={worker['profile_dir']}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
        f"--disable-extensions-except={worker['extension_dir']}",
        f"--load-extension={worker['extension_dir']}",
        "--new-window",
        options.start_url,
    ]
    logging.info(
        "Launching Brave worker %s with %s on port %s.",
        worker["worker_number"],
        proxy_config.safe_label(),
        worker["port"],
    )
    return subprocess.Popen(args)


def create_proxy_auth_extension(extension_dir: Path, proxy_config: ProxyConfig) -> None:
    parsed = urlsplit(proxy_config.server)
    if not parsed.hostname or not parsed.port:
        raise RuntimeError(f"Invalid proxy server for {proxy_config.safe_label()}: {proxy_config.server}")
    scheme = normalize_proxy_scheme(parsed.scheme)
    extension_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "manifest_version": 3,
        "name": f"Tripadvisor proxy profile {proxy_config.safe_label()}",
        "version": "1.0.0",
        "permissions": ["proxy", "storage", "unlimitedStorage", "webRequest"],
        "host_permissions": ["<all_urls>"],
        "background": {"service_worker": "background.js"},
        "minimum_chrome_version": "108.0.0",
    }
    if proxy_config.username or proxy_config.password:
        manifest["permissions"].append("webRequestAuthProvider")

    auth_listener = ""
    if proxy_config.username or proxy_config.password:
        auth_listener = f"""
chrome.webRequest.onAuthRequired.addListener(
  (details, callback) => {{
    callback({{
      authCredentials: {{
        username: {json.dumps(proxy_config.username or "")},
        password: {json.dumps(proxy_config.password or "")}
      }}
    }});
  }},
  {{ urls: ["<all_urls>"] }},
  ["asyncBlocking"]
);
"""

    background = f"""
const proxyConfig = {{
  mode: "fixed_servers",
  rules: {{
    singleProxy: {{
      scheme: {json.dumps(scheme)},
      host: {json.dumps(parsed.hostname)},
      port: {int(parsed.port)}
    }},
    bypassList: ["localhost", "127.0.0.1"]
  }}
}};

chrome.proxy.settings.set({{ value: proxyConfig, scope: "regular" }});
{auth_listener}
"""
    (extension_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (extension_dir / "background.js").write_text(background.strip() + "\n", encoding="utf-8")


def normalize_proxy_scheme(scheme: str) -> str:
    lowered = (scheme or "http").lower()
    if lowered in {"socks5", "socks"}:
        return "socks5"
    if lowered in {"https", "http"}:
        return lowered
    return "http"


def wait_for_cdp(port: int, timeout_seconds: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://127.0.0.1:{port}/json/version"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as error:
            last_error = error
            time.sleep(0.5)
    raise RuntimeError(f"CDP port {port} did not become ready: {last_error}")


def print_plan(workers: list[dict], options: ParallelCDPOptions) -> None:
    print("Parallel Tripadvisor CDP plan:")
    print(f"- workers: {len(workers)}")
    if options.distributed_slot_count is not None:
        slot_end = options.distributed_slot_start + len(workers) - 1
        print(
            f"- distributed slots: total={options.distributed_slot_count} "
            f"local_zero_based={options.distributed_slot_start}-{slot_end}"
        )
    print(f"- input partial: {options.input_partial_path}")
    print(f"- output root: {options.output_root}")
    print(f"- profile root: {options.profile_root}")
    for worker in workers:
        print(
            f"- worker {worker['worker_number']}/{worker['worker_count']}: "
            f"slot={worker['distributed_slot']}/{worker['shard_count']} "
            f"{worker['proxy'].safe_label()} port={worker['port']} "
            f"profile={worker['profile_dir']} output={worker['output_dir']}"
        )
    print("Worker commands:")
    for worker in workers:
        print(" ".join(quote_arg(part) for part in worker["command"]))


def quote_arg(value: object) -> str:
    text = str(value)
    if not text or any(char.isspace() for char in text):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def default_parallel_profile_root(project_root: Path) -> Path:
    if os.name == "nt":
        return Path("C:/tmp/tripadvisor_cdp_proxy_profiles")
    return project_root / "output" / "cdp_proxy_profiles"


def unique_run_output_root(base_output_root: Path) -> Path:
    timestamp = timestamp_for_filename()
    candidate = base_output_root / f"run_{timestamp}"
    suffix = 2
    while candidate.exists():
        candidate = base_output_root / f"run_{timestamp}_{suffix}"
        suffix += 1
    return candidate
