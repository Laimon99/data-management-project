from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Page, sync_playwright

from . import config
from .scraper import TripadvisorScraper, count_pending_details
from .storage import JsonStorage
from .validators import build_validation_report


@dataclass(frozen=True, slots=True)
class CDPDetailOptions:
    connect_over_cdp_url: str
    max_records: int | None = None
    delay_min_seconds: float | None = None
    delay_max_seconds: float | None = None
    partial_every_records: int = config.SAVE_PARTIAL_EVERY_N_RESTAURANTS
    max_consecutive_failures: int = 3
    detail_shard_count: int = 1
    detail_shard_index: int = 1
    human_scroll_enabled: bool = True


def run_cdp_detail_enrichment(storage: JsonStorage, options: CDPDetailOptions) -> dict[str, Any]:
    records = storage.load_partial()
    if not records:
        raise RuntimeError("No partial records found. Run listing scraping or pass --input-partial first.")

    scraper = TripadvisorScraper(
        storage=storage,
        headless=False,
        scrape_detail_pages=True,
        detail_delay_min_seconds=options.delay_min_seconds,
        detail_delay_max_seconds=options.delay_max_seconds,
        human_scroll_enabled=options.human_scroll_enabled,
        partial_every_restaurants=options.partial_every_records,
        max_consecutive_detail_failures=options.max_consecutive_failures,
        detail_shard_count=options.detail_shard_count,
        detail_shard_index=options.detail_shard_index,
    )
    pending_indexes = scraper._pending_detail_indexes(records)
    if options.max_records is not None:
        pending_indexes = pending_indexes[: max(0, options.max_records)]

    report: dict[str, Any] = {
        "source": "tripadvisor",
        "mode": "cdp_detail",
        "connect_over_cdp_url": options.connect_over_cdp_url,
        "initial_total_records": len(records),
        "detail_shard_count": options.detail_shard_count,
        "detail_shard_index": options.detail_shard_index,
        "initial_pending_in_scope": len(pending_indexes),
        "max_records": options.max_records,
        "attempted_scope": 0,
        "stopped_reason": None,
    }

    if not pending_indexes:
        logging.info("No pending Tripadvisor detail records matched the configured scope.")
        storage.save_partial(records)
        storage.save_validation_report(build_validation_report(records))
        return report

    logging.info("Starting Tripadvisor CDP detail enrichment for %s pending records.", len(pending_indexes))
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(options.connect_over_cdp_url)
        try:
            page = find_tripadvisor_page(browser.contexts)
            if page is None:
                raise RuntimeError("No open Tripadvisor tab found in the connected browser.")

            max_detail_records = options.max_records if options.max_records is not None else None
            records = scraper._scrape_detail_pages(page, records, max_detail_records=max_detail_records)
            report["attempted_scope"] = min(len(pending_indexes), max_detail_records or len(pending_indexes))
        finally:
            browser.close()

    storage.save_partial(records)
    storage.save_validation_report(build_validation_report(records))
    pending_global = count_pending_details(records)
    report["remaining_pending_global"] = pending_global
    report["detail_scraped"] = len(records) - pending_global
    if pending_global == 0:
        storage.save_final(records)
    logging.info(
        "Tripadvisor CDP detail enrichment finished. detail_scraped=%s remaining_global=%s",
        report["detail_scraped"],
        pending_global,
    )
    return report


def find_tripadvisor_page(contexts: Any) -> Page | None:
    pages = [page for context in contexts for page in context.pages]
    for page in pages:
        if "tripadvisor." in page.url:
            return page
    return pages[0] if pages else None
