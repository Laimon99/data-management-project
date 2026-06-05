from __future__ import annotations

import logging
import math
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from . import config
from .detail_scraper import TheForkDetailScraper
from .models import RestaurantRecord
from .parser import deduplication_key, parse_restaurant_card
from .proxy_utils import ProxyConfig, proxy_for_batch
from .storage import JsonStorage
from .validators import build_validation_report

START_URL = config.START_URL
RESTAURANT_LINK_SELECTOR = 'a[href*="/ristorante/"]'
RESTAURANT_HREF_PATTERN = re.compile(r"/ristorante/[^/?#]+-r\d+", re.IGNORECASE)
DEFAULT_BROWSER_CHANNELS: tuple[str | None, ...] = ("chrome", "msedge", None)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class AccessBlockedError(RuntimeError):
    pass


class TheForkScraper:
    def __init__(
        self,
        storage: JsonStorage,
        start_url: str = START_URL,
        browser_channel: str | None = None,
        browser_executable_path: str | None = None,
        headless: bool = True,
        delay_seconds: float = 1.5,
        partial_every_pages: int = 5,
        partial_every_restaurants: int = config.SAVE_PARTIAL_EVERY_N_RESTAURANTS,
        max_empty_pages: int = 3,
        navigation_timeout_ms: int = 60_000,
        card_timeout_ms: int = 30_000,
        scrape_detail_pages: bool = config.SCRAPE_DETAIL_PAGES,
        detail_delay_seconds: float = config.DELAY_BETWEEN_DETAIL_PAGES_SECONDS,
        detail_delay_min_seconds: float | None = None,
        detail_delay_max_seconds: float | None = None,
        human_scroll_enabled: bool = False,
        pause_on_antibot: bool = False,
        micro_pause_min_ms: int = 0,
        micro_pause_max_ms: int = 0,
        max_reviews_per_restaurant: int = config.MAX_REVIEWS_PER_RESTAURANT,
        resume_detail: bool = False,
        max_consecutive_detail_failures: int = 10,
        auto_detail_until_complete: bool = False,
        detail_batch_size: int = config.DETAIL_BATCH_SIZE,
        detail_shard_count: int = 1,
        detail_shard_index: int = 1,
        cooldown_seconds: int = config.COOLDOWN_SECONDS,
        max_cooldown_seconds: int = config.MAX_COOLDOWN_SECONDS,
        cooldown_multiplier: float = config.COOLDOWN_MULTIPLIER,
        max_auto_detail_cycles: int = config.MAX_AUTO_DETAIL_CYCLES,
        save_final_incomplete: bool = False,
        proxy_configs: list[ProxyConfig] | None = None,
        user_data_dir: Path | None = None,
        proxy_burn_through: bool = False,
        include_direct_ip_after_proxies: bool = False,
        proxy_round_robin: bool = False,
        restaurants_per_proxy_turn: int = 1,
        proxy_min_rest_seconds: float = 900.0,
        proxy_403_cooldown_seconds: float = 10800.0,
        pool_403_threshold: int = 3,
        pool_403_window_seconds: float = 900.0,
        pool_403_cooldown_seconds: float = 21600.0,
        stop_on_pool_block: bool = True,
        proxy_max_failed_turns: int = 3,
        proxy_turn_jitter_seconds: float = 30.0,
        max_url_failures_before_deferral: int = 1,
        deferred_url_retry_cycles: int = 300,
        browser_warmup_url: str | None = None,
        browser_warmup_seconds: float = 0.0,
    ) -> None:
        self.storage = storage
        self.start_url = start_url
        self.browser_channel = normalize_browser_channel(browser_channel)
        self.browser_executable_path = browser_executable_path
        self.headless = headless
        self.delay_seconds = delay_seconds
        self.partial_every_pages = max(1, partial_every_pages)
        self.partial_every_restaurants = max(1, partial_every_restaurants)
        self.max_empty_pages = max(1, max_empty_pages)
        self.navigation_timeout_ms = navigation_timeout_ms
        self.card_timeout_ms = card_timeout_ms
        self.scrape_detail_pages = scrape_detail_pages
        self.detail_delay_seconds = detail_delay_seconds
        self.detail_delay_min_seconds = detail_delay_min_seconds
        self.detail_delay_max_seconds = detail_delay_max_seconds
        self.human_scroll_enabled = human_scroll_enabled
        self.pause_on_antibot = pause_on_antibot
        self.micro_pause_min_ms = max(0, micro_pause_min_ms)
        self.micro_pause_max_ms = max(self.micro_pause_min_ms, micro_pause_max_ms)
        self.max_reviews_per_restaurant = max_reviews_per_restaurant
        self.resume_detail = resume_detail
        self.max_consecutive_detail_failures = max(1, max_consecutive_detail_failures)
        self.auto_detail_until_complete = auto_detail_until_complete
        self.detail_batch_size = max(1, detail_batch_size)
        self.detail_shard_count = max(1, detail_shard_count)
        self.detail_shard_index = min(max(1, detail_shard_index), self.detail_shard_count)
        self.cooldown_seconds = max(0, cooldown_seconds)
        self.max_cooldown_seconds = max(self.cooldown_seconds, max_cooldown_seconds)
        self.cooldown_multiplier = max(1.0, cooldown_multiplier)
        self.max_auto_detail_cycles = max(1, max_auto_detail_cycles)
        self.save_final_incomplete = save_final_incomplete
        self.proxy_configs = proxy_configs or []
        self.user_data_dir = user_data_dir
        self.proxy_burn_through = proxy_burn_through
        self.include_direct_ip_after_proxies = include_direct_ip_after_proxies
        self.proxy_round_robin = proxy_round_robin
        self.restaurants_per_proxy_turn = max(1, restaurants_per_proxy_turn)
        self.proxy_min_rest_seconds = max(0.0, proxy_min_rest_seconds)
        self.proxy_403_cooldown_seconds = max(0.0, proxy_403_cooldown_seconds)
        self.pool_403_threshold = max(1, pool_403_threshold)
        self.pool_403_window_seconds = max(1.0, pool_403_window_seconds)
        self.pool_403_cooldown_seconds = max(0.0, pool_403_cooldown_seconds)
        self.stop_on_pool_block = stop_on_pool_block
        self.proxy_max_failed_turns = max(1, proxy_max_failed_turns)
        self.proxy_turn_jitter_seconds = max(0.0, proxy_turn_jitter_seconds)
        self.max_url_failures_before_deferral = max(1, max_url_failures_before_deferral)
        self.deferred_url_retry_cycles = max(1, deferred_url_retry_cycles)
        self.browser_warmup_url = browser_warmup_url
        self.browser_warmup_seconds = max(0.0, browser_warmup_seconds)
        self.detail_batch_counter = 0
        self.detail_stopped_early = False

    def scrape(
        self, max_pages: int | None = None, max_restaurants: int | None = None
    ) -> list[RestaurantRecord]:
        if self.proxy_round_robin:
            return self._proxy_round_robin_until_complete(
                max_pages=max_pages, max_restaurants=max_restaurants
            )

        if self.proxy_burn_through:
            return self._proxy_burn_through_until_complete(
                max_pages=max_pages, max_restaurants=max_restaurants
            )

        if self.auto_detail_until_complete:
            return self._auto_detail_until_complete(
                max_pages=max_pages, max_restaurants=max_restaurants
            )

        channels = self._candidate_channels()
        last_error: Exception | None = None

        for channel in channels:
            channel_name = channel or "bundled chromium"
            logging.info("Starting scraper with browser channel: %s", channel_name)
            try:
                return self._scrape_with_channel(channel, max_pages, max_restaurants)
            except AccessBlockedError as error:
                last_error = error
                logging.warning(
                    "%s was blocked or returned no listing content: %s", channel_name, error
                )
            except PlaywrightError as error:
                last_error = error
                logging.warning("Could not use browser channel %s: %s", channel_name, error)

        raise RuntimeError(
            "The scraper could not load TheFork with any configured browser channel."
        ) from last_error

    def _candidate_channels(self) -> list[str | None]:
        if self.browser_executable_path:
            return [None]
        if self.browser_channel is not None:
            return [self.browser_channel]
        return list(DEFAULT_BROWSER_CHANNELS)

    def _scrape_with_channel(
        self,
        browser_channel: str | None,
        max_pages: int | None,
        max_restaurants: int | None,
        save_final: bool = True,
    ) -> list[RestaurantRecord]:
        records_by_key: dict[str, RestaurantRecord] = {}
        detected_max_page: int | None = None
        consecutive_empty_pages = 0
        scraped_at = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )

        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {
                "headless": self.headless,
                "chromium_sandbox": True,
                "args": []
                if self.browser_executable_path
                else ["--disable-blink-features=AutomationControlled"],
            }
            if self.browser_executable_path:
                launch_options["executable_path"] = self.browser_executable_path
            elif browser_channel is not None:
                launch_options["channel"] = browser_channel
            proxy = proxy_for_batch(self.proxy_configs, 1)
            if proxy is not None:
                logging.info("Using proxy for browser session: %s", proxy.safe_label())
                launch_options["proxy"] = proxy.to_playwright()

            browser = None
            context_options: dict[str, Any] = {
                "locale": "it-IT",
                "timezone_id": "Europe/Rome",
                "viewport": {"width": 1440, "height": 1800},
                "user_agent": DEFAULT_USER_AGENT,
                "extra_http_headers": {"Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"},
            }
            if self.user_data_dir is not None:
                profile_dir = profile_dir_for_proxy(self.user_data_dir, proxy)
                profile_dir.mkdir(parents=True, exist_ok=True)
                logging.info("Using persistent browser profile: %s", profile_dir)
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    **launch_options,
                    **context_options,
                )
            else:
                browser = playwright.chromium.launch(**launch_options)
                context = browser.new_context(**context_options)
            page = context.new_page()
            page.set_default_timeout(self.card_timeout_ms)
            page.set_default_navigation_timeout(self.navigation_timeout_ms)

            try:
                if self.resume_detail:
                    self._warm_up_browser_profile(page)
                    records = self.storage.load_partial()
                    if max_restaurants is not None:
                        records = records[:max_restaurants]
                    if not records:
                        raise RuntimeError(
                            "Cannot resume detail scraping because the partial output "
                            "is missing or empty."
                        )
                    records = self._scrape_detail_pages(page, records)
                    self.storage.save_partial(records)
                    if save_final and (not self.detail_stopped_early or self.save_final_incomplete):
                        self.storage.save_final(records)
                    elif self.detail_stopped_early:
                        logging.warning(
                            "Final output was not overwritten because detail scraping "
                            "stopped early."
                        )
                    self.storage.save_validation_report(build_validation_report(records))
                    return records

                page_number = 1
                processed_pages = 0
                while True:
                    if max_pages is not None and processed_pages >= max_pages:
                        logging.info("Reached configured page limit: %s", max_pages)
                        break

                    if detected_max_page is not None and page_number > detected_max_page:
                        logging.info("Reached detected last listing page: %s", detected_max_page)
                        break

                    page_url = build_listing_url(self.start_url, page_number)
                    logging.info("Loading listing page %s: %s", page_number, page_url)
                    response_status = self._load_page(page, page_url)
                    if response_status == 403:
                        raise AccessBlockedError("HTTP 403 while loading the listing page")

                    self._handle_cookie_popup(page)
                    self._wait_for_cards(page)
                    self._scroll_listing(page)

                    card_payloads = self._extract_card_payloads(page)
                    if page_number == 1 and not card_payloads:
                        raise AccessBlockedError(
                            "No restaurant links were found on the first listing page"
                        )

                    page_records = self._parse_page_records(card_payloads, scraped_at, page_number)
                    new_count = self._merge_records(records_by_key, page_records)
                    processed_pages += 1

                    detected_max_page = detected_max_page or self._detect_max_page(
                        page, len(card_payloads)
                    )
                    total_records = len(records_by_key)
                    logging.info(
                        "Page %s parsed: %s cards, %s valid records, "
                        "%s new records, %s total records",
                        page_number,
                        len(card_payloads),
                        len(page_records),
                        new_count,
                        total_records,
                    )

                    if should_save_partial(processed_pages, self.partial_every_pages):
                        self.storage.save_partial(list(records_by_key.values()))

                    if new_count == 0:
                        consecutive_empty_pages += 1
                        logging.warning(
                            "Page %s produced no new restaurants. Consecutive empty pages: %s/%s",
                            page_number,
                            consecutive_empty_pages,
                            self.max_empty_pages,
                        )
                    else:
                        consecutive_empty_pages = 0

                    if consecutive_empty_pages >= self.max_empty_pages:
                        logging.warning(
                            "Stopping after too many consecutive pages without new restaurants."
                        )
                        break

                    if max_restaurants is not None and total_records >= max_restaurants:
                        logging.info("Reached configured restaurant limit: %s", max_restaurants)
                        break

                    page_number += 1
                    if self.delay_seconds > 0:
                        time.sleep(self.delay_seconds)

                records = list(records_by_key.values())
                if max_restaurants is not None:
                    records = records[:max_restaurants]

                if self.scrape_detail_pages:
                    self._warm_up_browser_profile(page)
                    records = self._scrape_detail_pages(page, records)

                self.storage.save_partial(records)
                if save_final and (not self.detail_stopped_early or self.save_final_incomplete):
                    self.storage.save_final(records)
                elif self.detail_stopped_early:
                    logging.warning(
                        "Final output was not overwritten because detail scraping stopped early."
                    )
                self.storage.save_validation_report(build_validation_report(records))
                return records
            finally:
                context.close()
                if browser is not None:
                    browser.close()

    def _load_page(self, page: Page, page_url: str) -> int | None:
        try:
            response = page.goto(
                page_url, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms
            )
            return response.status if response else None
        except PlaywrightTimeoutError:
            logging.warning("Timed out while loading %s", page_url)
            return None

    def _warm_up_browser_profile(self, page: Page) -> None:
        if not self.browser_warmup_url and self.browser_warmup_seconds <= 0:
            return

        target_url = self.browser_warmup_url or self.start_url
        logging.info(
            "Warming up browser profile on %s for %.1f seconds.",
            target_url,
            self.browser_warmup_seconds,
        )
        try:
            self._load_page(page, target_url)
            self._handle_cookie_popup(page)
            page.wait_for_timeout(2500)
            page.mouse.wheel(0, random.randint(320, 620))
            page.wait_for_timeout(random.randint(900, 1600))
            page.mouse.wheel(0, random.randint(240, 520))
            if self.browser_warmup_seconds > 0:
                page.wait_for_timeout(int(self.browser_warmup_seconds * 1000))
        except PlaywrightError as error:
            logging.warning("Browser warm-up failed, continuing with detail scraping: %s", error)

    def _handle_cookie_popup(self, page: Page) -> None:
        button_names = [
            r"^ACCETTO$",
            r"^Accetta tutto$",
            r"^Accetta tutti$",
            r"^Accept all$",
            r"^I agree$",
            r"^OK$",
        ]
        for button_name in button_names:
            try:
                button = page.get_by_role(
                    "button", name=re.compile(button_name, re.IGNORECASE)
                ).first
                if button.count() and button.is_visible(timeout=1_000):
                    button.click(timeout=3_000)
                    logging.info("Accepted or dismissed the cookie popup.")
                    page.wait_for_timeout(1_000)
                    return
            except PlaywrightError:
                continue

    def _wait_for_cards(self, page: Page) -> None:
        try:
            page.wait_for_selector(RESTAURANT_LINK_SELECTOR, timeout=self.card_timeout_ms)
        except PlaywrightTimeoutError:
            logging.warning("No restaurant links became visible before the timeout.")

    def _scroll_listing(self, page: Page) -> None:
        try:
            previous_count = -1
            stable_iterations = 0
            for _ in range(30):
                state = page.evaluate(
                    """
                    () => ({
                      y: window.scrollY,
                      height: document.body.scrollHeight,
                      viewport: window.innerHeight,
                      count: document.querySelectorAll('a[href*="/ristorante/"]').length,
                    })
                    """
                )
                current_count = int(state["count"])
                if current_count == previous_count:
                    stable_iterations += 1
                else:
                    stable_iterations = 0

                is_at_bottom = state["y"] + state["viewport"] >= state["height"] - 50
                if is_at_bottom and stable_iterations >= 2:
                    break

                previous_count = current_count
                page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.8))")
                page.wait_for_timeout(500)
        except PlaywrightError as error:
            logging.warning("Could not scroll the listing page: %s", error)

    def _extract_card_payloads(self, page: Page) -> list[dict[str, str | None]]:
        return page.evaluate(
            """
            () => {
              const linkSelector = 'a[href*="/ristorante/"]';
              const restaurantPattern = /\\/ristorante\\/[^/?#]+-r\\d+/i;
              const clean = (value) => (value || '').trim();
              const hasCardSignal = (text) => (
                /\\bMilano\\b/i.test(text) ||
                /Prezzo\\s+medio/i.test(text) ||
                /\\b[0-9][,.][0-9]\\b/.test(text)
              );
              const bestTextForLink = (anchor) => {
                const anchorText = clean(anchor.innerText || anchor.textContent || '');
                if (anchorText.length >= 30 && hasCardSignal(anchorText)) {
                  return anchorText;
                }

                let node = anchor.parentElement;
                for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
                  const candidateText = clean(node.innerText || '');
                  const restaurantLinkCount = node.querySelectorAll(linkSelector).length;
                  if (
                    candidateText.length >= 30 &&
                    candidateText.length <= 1600 &&
                    restaurantLinkCount <= 4 &&
                    hasCardSignal(candidateText)
                  ) {
                    return candidateText;
                  }
                }
                return anchorText;
              };

              const seen = new Set();
              return Array.from(document.querySelectorAll(linkSelector))
                .filter((anchor) =>
                  restaurantPattern.test(anchor.getAttribute('href') || anchor.href || '')
                )
                .map((anchor) => ({
                  href: anchor.href || anchor.getAttribute('href'),
                  aria_label: anchor.getAttribute('aria-label'),
                  text: bestTextForLink(anchor),
                }))
                .filter((payload) => {
                  const key = (payload.href || '').replace(/[?#].*$/, '');
                  if (!key || seen.has(key)) {
                    return false;
                  }
                  seen.add(key);
                  return true;
                });
            }
            """
        )

    def _parse_page_records(
        self,
        card_payloads: list[dict[str, str | None]],
        scraped_at: str,
        page_number: int,
    ) -> list[RestaurantRecord]:
        records: list[RestaurantRecord] = []
        for payload in card_payloads:
            record = parse_restaurant_card(
                restaurant_url=payload.get("href") or "",
                card_text=payload.get("text") or "",
                aria_label=payload.get("aria_label"),
                scraped_at=scraped_at,
                source_page_number=page_number,
            )
            if record is not None:
                records.append(record)
        return records

    def _merge_records(
        self,
        records_by_key: dict[str, RestaurantRecord],
        page_records: list[RestaurantRecord],
    ) -> int:
        new_count = 0
        for record in page_records:
            key = deduplication_key(record)
            if key not in records_by_key:
                records_by_key[key] = record
                new_count += 1
        return new_count

    def _auto_detail_until_complete(
        self,
        max_pages: int | None,
        max_restaurants: int | None,
    ) -> list[RestaurantRecord]:
        channel = self._candidate_channels()[0]
        records = self.storage.load_partial()

        if not records:
            logging.info(
                "No partial output found. Collecting listing data before detail auto-resume."
            )
            original_scrape_detail_pages = self.scrape_detail_pages
            original_resume_detail = self.resume_detail
            try:
                self.scrape_detail_pages = False
                self.resume_detail = False
                records = self._scrape_with_channel(
                    channel,
                    max_pages=max_pages,
                    max_restaurants=max_restaurants,
                    save_final=False,
                )
            finally:
                self.scrape_detail_pages = original_scrape_detail_pages
                self.resume_detail = original_resume_detail

        cooldown_seconds = self.cooldown_seconds
        previous_remaining = count_pending_details(records)
        blocked_proxy_cycles = 0

        for cycle in range(1, self.max_auto_detail_cycles + 1):
            remaining = count_pending_details(records)
            logging.info(
                "Auto detail cycle %s/%s: %s records still need detail scraping.",
                cycle,
                self.max_auto_detail_cycles,
                remaining,
            )
            if remaining == 0:
                self.storage.save_partial(records)
                self.storage.save_final(records)
                self.storage.save_validation_report(build_validation_report(records))
                logging.info("All TheFork detail pages have been scraped.")
                return records

            self.detail_stopped_early = False
            records = self._scrape_detail_batch_with_channel(channel, records)
            self.storage.save_partial(records)
            self.storage.save_validation_report(build_validation_report(records))

            remaining = count_pending_details(records)
            if remaining == 0:
                self.storage.save_final(records)
                logging.info("All TheFork detail pages have been scraped.")
                return records

            made_progress = remaining < previous_remaining
            previous_remaining = remaining
            if self.detail_stopped_early or not made_progress:
                if self.proxy_configs and blocked_proxy_cycles < len(self.proxy_configs) - 1:
                    blocked_proxy_cycles += 1
                    logging.warning(
                        "TheFork detail batch was blocked or made no progress. "
                        "Rotating to the next proxy without a full cooldown "
                        "(%s/%s blocked proxy batches).",
                        blocked_proxy_cycles,
                        len(self.proxy_configs),
                    )
                    time.sleep(min(30, max(1, self.detail_delay_seconds)))
                    continue

                logging.warning(
                    "TheFork detail scraping is blocked or made no progress. "
                    "Cooling down for %s seconds before retrying.",
                    cooldown_seconds,
                )
                if cooldown_seconds > 0:
                    time.sleep(cooldown_seconds)
                cooldown_seconds = min(
                    self.max_cooldown_seconds,
                    int(max(cooldown_seconds + 1, cooldown_seconds * self.cooldown_multiplier)),
                )
                blocked_proxy_cycles = 0
            else:
                blocked_proxy_cycles = 0
                cooldown_seconds = self.cooldown_seconds

        logging.warning(
            "Stopped auto detail mode after %s cycles with %s records still incomplete.",
            self.max_auto_detail_cycles,
            count_pending_details(records),
        )
        self.storage.save_partial(records)
        self.storage.save_validation_report(build_validation_report(records))
        if self.save_final_incomplete:
            self.storage.save_final(records)
        return records

    def _proxy_burn_through_until_complete(
        self,
        max_pages: int | None,
        max_restaurants: int | None,
    ) -> list[RestaurantRecord]:
        records = self.storage.load_partial()
        record_limit = (
            min(max_restaurants, len(records)) if max_restaurants is not None and records else None
        )

        if not records:
            logging.info(
                "No partial output found. Collecting listing data "
                "before proxy burn-through detail scraping."
            )
            original_scrape_detail_pages = self.scrape_detail_pages
            original_resume_detail = self.resume_detail
            try:
                self.scrape_detail_pages = False
                self.resume_detail = False
                records = self._scrape_with_channel(
                    self._candidate_channels()[0],
                    max_pages=max_pages,
                    max_restaurants=max_restaurants,
                    save_final=False,
                )
            finally:
                self.scrape_detail_pages = original_scrape_detail_pages
                self.resume_detail = original_resume_detail
            record_limit = (
                min(max_restaurants, len(records))
                if max_restaurants is not None and records
                else None
            )

        proxy_sequence: list[ProxyConfig | None] = list(self.proxy_configs)
        if self.include_direct_ip_after_proxies or not proxy_sequence:
            proxy_sequence.append(None)

        report = {
            "source": "thefork",
            "started_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "mode": "proxy_burn_through",
            "initial_total_records": len(records),
            "record_limit": record_limit,
            "initial_pending_details": count_pending_details(records, record_limit),
            "max_consecutive_failures": self.max_consecutive_detail_failures,
            "detail_delay_seconds": self.detail_delay_seconds,
            "proxy_results": [],
        }
        self.storage.save_proxy_progress_report(report)

        for proxy_index, proxy in enumerate(proxy_sequence, start=1):
            pending_before = count_pending_details(records, record_limit)
            if pending_before == 0:
                break

            proxy_label = proxy.safe_label() if proxy else "direct_ip"
            logging.info(
                "Starting TheFork proxy burn-through %s/%s with %s. Pending details: %s",
                proxy_index,
                len(proxy_sequence),
                proxy_label,
                pending_before,
            )
            started_at = time.monotonic()
            result = self._scrape_until_proxy_blocked(
                self._candidate_channels()[0], records, proxy, record_limit
            )
            records = result.pop("records")
            pending_after = count_pending_details(records, record_limit)
            result.update(
                {
                    "proxy_label": proxy_label,
                    "proxy_index": proxy_index,
                    "pending_before": pending_before,
                    "pending_after": pending_after,
                    "completed_with_this_proxy": pending_before - pending_after,
                    "duration_seconds": round(time.monotonic() - started_at, 3),
                    "retired": result.get("stopped_by_failures", False),
                }
            )
            report["proxy_results"].append(result)
            report["latest_pending_details"] = pending_after
            report["latest_detail_completed"] = (record_limit or len(records)) - pending_after
            self.storage.save_partial(records)
            self.storage.save_validation_report(build_validation_report(records))
            self.storage.save_proxy_progress_report(report)

            if pending_after == 0:
                if record_limit is None:
                    self.storage.save_final(records)
                    logging.info("All TheFork detail pages have been scraped.")
                else:
                    logging.info(
                        "The configured restaurant limit has no pending TheFork detail records."
                    )
                return records

            if result["completed_with_this_proxy"] == 0:
                logging.warning(
                    "Proxy %s produced no completed detail records before retirement.", proxy_label
                )

        remaining = count_pending_details(records, record_limit)
        logging.warning(
            "Proxy burn-through ended with %s pending TheFork detail records.", remaining
        )
        self.storage.save_partial(records)
        self.storage.save_validation_report(build_validation_report(records))
        self.storage.save_proxy_progress_report(report)
        if (remaining == 0 and record_limit is None) or self.save_final_incomplete:
            self.storage.save_final(records)
        return records

    def _scrape_until_proxy_blocked(
        self,
        browser_channel: str | None,
        records: list[RestaurantRecord],
        proxy: ProxyConfig | None,
        record_limit: int | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "stopped_by_failures": False,
            "records": records,
        }
        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {
                "headless": self.headless,
                "chromium_sandbox": True,
                "args": []
                if self.browser_executable_path
                else ["--disable-blink-features=AutomationControlled"],
            }
            if self.browser_executable_path:
                launch_options["executable_path"] = self.browser_executable_path
            elif browser_channel is not None:
                launch_options["channel"] = browser_channel
            if proxy is not None:
                logging.info("Using proxy for burn-through run: %s", proxy.safe_label())
                launch_options["proxy"] = proxy.to_playwright()

            browser = None
            context_options: dict[str, Any] = {
                "locale": "it-IT",
                "timezone_id": "Europe/Rome",
                "viewport": {"width": 1440, "height": 1800},
                "user_agent": DEFAULT_USER_AGENT,
                "extra_http_headers": {"Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"},
            }
            if self.user_data_dir is not None:
                profile_dir = profile_dir_for_proxy(self.user_data_dir, proxy)
                profile_dir.mkdir(parents=True, exist_ok=True)
                logging.info("Using persistent browser profile: %s", profile_dir)
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    **launch_options,
                    **context_options,
                )
            else:
                browser = playwright.chromium.launch(**launch_options)
                context = browser.new_context(**context_options)

            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(self.card_timeout_ms)
            page.set_default_navigation_timeout(self.navigation_timeout_ms)
            try:
                self._warm_up_browser_profile(page)
                detail_scraper = self._create_detail_scraper()
                detail_scraped_at = (
                    datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                consecutive_failures = 0
                for index, record in enumerate(records, start=1):
                    if record_limit is not None and index > record_limit:
                        break
                    if record.detail_scraped:
                        continue

                    logging.info(
                        "Burn-through detail attempt with %s: record %s/%s %s",
                        proxy.safe_label() if proxy else "direct_ip",
                        index,
                        len(records),
                        record.restaurant_url,
                    )
                    enriched_record = detail_scraper.enrich_record(page, record, detail_scraped_at)
                    records[index - 1] = enriched_record
                    result["attempted"] += 1

                    if enriched_record.detail_scraped:
                        result["succeeded"] += 1
                        consecutive_failures = 0
                    else:
                        result["failed"] += 1
                        consecutive_failures += 1

                    if index == 1 or index % self.partial_every_restaurants == 0:
                        self.storage.save_partial(records)

                    if consecutive_failures >= self.max_consecutive_detail_failures:
                        result["stopped_by_failures"] = True
                        logging.warning(
                            "Retiring current proxy after %s consecutive detail failures.",
                            consecutive_failures,
                        )
                        break

                    self._wait_between_detail_pages(page)

                result["records"] = records
                return result
            finally:
                context.close()
                if browser is not None:
                    browser.close()

    def _proxy_round_robin_until_complete(
        self,
        max_pages: int | None,
        max_restaurants: int | None,
    ) -> list[RestaurantRecord]:
        channel = self._candidate_channels()[0]
        records = self.storage.load_partial()
        record_limit = (
            min(max_restaurants, len(records)) if max_restaurants is not None and records else None
        )
        deferrals = self.storage.load_detail_deferrals()
        proxy_state = normalize_proxy_state(self.storage.load_proxy_state())
        proxy_state["recent_403_events"] = prune_recent_403_events(
            proxy_state.get("recent_403_events", []),
            self.pool_403_window_seconds,
        )
        restored_deferrals = restore_deferred_urls(
            deferrals,
            max_failures=self.max_url_failures_before_deferral,
            retry_cycles=self.deferred_url_retry_cycles,
        )
        if restored_deferrals:
            logging.info(
                "Restored %s previously failed detail URLs to deferred state.", restored_deferrals
            )

        if not records:
            logging.info(
                "No partial output found. Collecting listing data "
                "before round-robin detail scraping."
            )
            original_scrape_detail_pages = self.scrape_detail_pages
            original_resume_detail = self.resume_detail
            try:
                self.scrape_detail_pages = False
                self.resume_detail = False
                records = self._scrape_with_channel(
                    channel,
                    max_pages=max_pages,
                    max_restaurants=max_restaurants,
                    save_final=False,
                )
            finally:
                self.scrape_detail_pages = original_scrape_detail_pages
                self.resume_detail = original_resume_detail
            record_limit = (
                min(max_restaurants, len(records))
                if max_restaurants is not None and records
                else None
            )

        proxy_sequence: list[ProxyConfig | None] = list(self.proxy_configs)
        if self.include_direct_ip_after_proxies or not proxy_sequence:
            proxy_sequence.append(None)
        if self.proxy_configs and self.user_data_dir is None:
            logging.warning(
                "Round-robin mode is running without a persistent user data directory. "
                "Use --user-data-dir data/raw/thefork/browser_profile to isolate "
                "browser profiles per proxy."
            )

        states: list[dict[str, Any]] = []
        for proxy_index, proxy in enumerate(proxy_sequence, start=1):
            proxy_label = proxy.safe_label() if proxy else "direct_ip"
            stored_proxy_state = proxy_state["proxies"].get(proxy_label) or {}
            blocked_until = future_timestamp_or_none(stored_proxy_state.get("blocked_until"))
            states.append(
                {
                    "proxy": proxy,
                    "proxy_index": proxy_index,
                    "proxy_label": proxy_label,
                    "turns": 0,
                    "attempted": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "failed_turns": 0,
                    "retired": False,
                    "retired_at": None,
                    "retire_reason": None,
                    "last_used_monotonic": 0.0,
                    "last_used_at": None,
                    "blocked_until_monotonic": monotonic_deadline_for_timestamp(blocked_until),
                    "blocked_until": blocked_until,
                    "http_403_count": int(stored_proxy_state.get("http_403_count") or 0),
                    "last_success_at": stored_proxy_state.get("last_success_at"),
                    "last_success_url": stored_proxy_state.get("last_success_url"),
                    "last_failure_at": stored_proxy_state.get("last_failure_at"),
                    "last_failure_url": stored_proxy_state.get("last_failure_url"),
                    "last_failure_reason": stored_proxy_state.get("last_failure_reason"),
                }
            )

        report: dict[str, Any] = {
            "source": "thefork",
            "started_at": utc_timestamp(),
            "updated_at": utc_timestamp(),
            "mode": "proxy_round_robin",
            "initial_total_records": len(records),
            "record_limit": record_limit,
            "initial_pending_details": count_pending_details(records, record_limit),
            "strategy": {
                "restaurants_per_proxy_turn": self.restaurants_per_proxy_turn,
                "proxy_min_rest_seconds": self.proxy_min_rest_seconds,
                "proxy_403_cooldown_seconds": self.proxy_403_cooldown_seconds,
                "pool_403_threshold": self.pool_403_threshold,
                "pool_403_window_seconds": self.pool_403_window_seconds,
                "pool_403_cooldown_seconds": self.pool_403_cooldown_seconds,
                "stop_on_pool_block": self.stop_on_pool_block,
                "proxy_max_failed_turns": self.proxy_max_failed_turns,
                "proxy_turn_jitter_seconds": self.proxy_turn_jitter_seconds,
                "detail_delay_seconds": self.detail_delay_seconds,
                "include_direct_ip_after_proxies": self.include_direct_ip_after_proxies,
                "max_url_failures_before_deferral": self.max_url_failures_before_deferral,
                "deferred_url_retry_cycles": self.deferred_url_retry_cycles,
            },
            "proxy_results": [serializable_proxy_state(state) for state in states],
            "deferred_url_count": count_deferred_urls(deferrals),
            "global_blocked_until": proxy_state.get("global_blocked_until"),
            "recent_403_events": summarize_recent_403_events(proxy_state),
            "events": [],
        }
        self.storage.save_proxy_progress_report(report)
        self.storage.save_detail_deferrals(deferrals)
        self.storage.save_proxy_state(proxy_state)

        if is_future_timestamp(proxy_state.get("global_blocked_until")):
            logging.warning(
                "The proxy pool is in global cooldown until %s. "
                "Stopping before making new requests.",
                proxy_state.get("global_blocked_until"),
            )
            report["updated_at"] = utc_timestamp()
            report["latest_pending_details"] = count_pending_details(records, record_limit)
            report["pool_block_active"] = True
            report["global_blocked_until"] = proxy_state.get("global_blocked_until")
            self.storage.save_partial(records)
            self.storage.save_validation_report(build_validation_report(records))
            self.storage.save_proxy_progress_report(report)
            return records

        for cycle in range(1, self.max_auto_detail_cycles + 1):
            pending_before = count_pending_details(records, record_limit)
            if pending_before == 0:
                self.storage.save_partial(records)
                self.storage.save_validation_report(build_validation_report(records))
                if record_limit is None:
                    self.storage.save_final(records)
                    logging.info("All TheFork detail pages have been scraped.")
                else:
                    logging.info(
                        "The configured restaurant limit has no pending TheFork detail records."
                    )
                return records

            active_states = [state for state in states if not state["retired"]]
            if not active_states:
                logging.warning(
                    "No active proxies remain. Round-robin mode is stopping "
                    "with %s pending details.",
                    pending_before,
                )
                break

            state = self._next_round_robin_proxy_state(active_states)
            wait_seconds = self._proxy_wait_seconds(state)
            if wait_seconds > 0:
                logging.info(
                    "Waiting %.1f seconds before reusing %s.",
                    wait_seconds,
                    state["proxy_label"],
                )
                time.sleep(wait_seconds)

            logging.info(
                "Round-robin proxy turn %s/%s with %s. Pending details: %s",
                cycle,
                self.max_auto_detail_cycles,
                state["proxy_label"],
                pending_before,
            )
            started_at = time.monotonic()
            result = self._scrape_proxy_turn(
                channel, records, state["proxy"], record_limit, deferrals, cycle
            )
            records = result.pop("records")
            duration_seconds = round(time.monotonic() - started_at, 3)
            pending_after = count_pending_details(records, record_limit)

            state["turns"] += 1
            state["attempted"] += result.get("attempted", 0)
            state["succeeded"] += result.get("succeeded", 0)
            state["failed"] += result.get("failed", 0)
            state["last_used_monotonic"] = time.monotonic()
            state["last_used_at"] = utc_timestamp()

            last_attempted_url = last_item(result.get("attempted_urls", []))
            last_succeeded_url = last_item(result.get("succeeded_urls", []))
            last_failed_url = last_item(result.get("failed_urls", []))
            if last_succeeded_url:
                record_proxy_success(proxy_state, state["proxy_label"], last_succeeded_url)
                state["last_success_at"] = proxy_state["proxies"][state["proxy_label"]].get(
                    "last_success_at"
                )
                state["last_success_url"] = last_succeeded_url
            elif result.get("failed", 0) > 0:
                record_proxy_failure(
                    proxy_state,
                    proxy_label=state["proxy_label"],
                    url=last_failed_url or last_attempted_url,
                    reason=result.get("last_failure_reason"),
                    http_status=result.get("last_failure_http_status"),
                )
                state["last_failure_at"] = proxy_state["proxies"][state["proxy_label"]].get(
                    "last_failure_at"
                )
                state["last_failure_url"] = last_failed_url or last_attempted_url
                state["last_failure_reason"] = result.get("last_failure_reason")

            http_403_failures = [
                failure
                for failure in result.get("failure_http_statuses", [])
                if failure.get("status") == 403
            ]
            block_failure = is_detail_block_failure(
                result.get("last_failure_http_status"),
                result.get("last_failure_reason"),
            )
            pool_block_triggered = False
            if block_failure:
                if not http_403_failures and last_failed_url:
                    logging.warning(
                        "Block marker detected with %s. Treating this proxy as cooling down.",
                        state["proxy_label"],
                    )
                state["http_403_count"] += len(http_403_failures)
                if self.proxy_403_cooldown_seconds > 0:
                    blocked_until_monotonic = time.monotonic() + self.proxy_403_cooldown_seconds
                    state["blocked_until_monotonic"] = max(
                        float(state.get("blocked_until_monotonic") or 0.0),
                        blocked_until_monotonic,
                    )
                    state["blocked_until"] = utc_timestamp_after(self.proxy_403_cooldown_seconds)
                    set_proxy_blocked_until(
                        proxy_state, state["proxy_label"], state["blocked_until"]
                    )
                    logging.warning(
                        "HTTP block with %s. Pausing this proxy until %s.",
                        state["proxy_label"],
                        state["blocked_until"],
                    )

            block_events = http_403_failures or (
                [
                    {
                        "url": last_failed_url or last_attempted_url,
                        "status": result.get("last_failure_http_status"),
                    }
                ]
                if block_failure
                else []
            )
            for failure in block_events:
                pool_block_triggered = (
                    record_proxy_403_event(
                        proxy_state,
                        proxy_label=state["proxy_label"],
                        url=failure.get("url"),
                        reason=result.get("last_failure_reason"),
                        http_status=failure.get("status"),
                        window_seconds=self.pool_403_window_seconds,
                        threshold=self.pool_403_threshold,
                        cooldown_seconds=self.pool_403_cooldown_seconds,
                    )
                    or pool_block_triggered
                )

            if result.get("succeeded", 0) > 0:
                state["failed_turns"] = 0
            else:
                state["failed_turns"] += 1

            if state["failed_turns"] >= self.proxy_max_failed_turns:
                state["retired"] = True
                state["retired_at"] = utc_timestamp()
                state["retire_reason"] = (
                    f"{state['failed_turns']} consecutive turns without a completed detail record"
                )
                logging.warning(
                    "Retiring %s after %s failed round-robin turns.",
                    state["proxy_label"],
                    state["failed_turns"],
                )

            event = {
                "cycle": cycle,
                "proxy_label": state["proxy_label"],
                "attempted": result.get("attempted", 0),
                "succeeded": result.get("succeeded", 0),
                "failed": result.get("failed", 0),
                "pending_before": pending_before,
                "pending_after": pending_after,
                "duration_seconds": duration_seconds,
                "error": result.get("error"),
                "blocked_or_failed_turn": result.get("blocked_or_failed_turn", False),
                "attempted_urls": result.get("attempted_urls", []),
                "succeeded_urls": result.get("succeeded_urls", []),
                "failed_urls": result.get("failed_urls", []),
                "failure_http_statuses": result.get("failure_http_statuses", []),
                "failure_reasons": result.get("failure_reasons", []),
                "failure_block_markers": result.get("failure_block_markers", []),
                "blocked_until": state.get("blocked_until"),
                "created_at": utc_timestamp(),
            }
            report["events"].append(event)
            report["events"] = report["events"][-500:]
            report["updated_at"] = utc_timestamp()
            report["latest_pending_details"] = pending_after
            report["latest_detail_completed"] = (record_limit or len(records)) - pending_after
            report["proxy_results"] = [
                serializable_proxy_state(current_state) for current_state in states
            ]
            report["deferred_url_count"] = count_deferred_urls(deferrals)
            report["deferred_urls"] = summarize_deferrals(deferrals)
            report["global_blocked_until"] = proxy_state.get("global_blocked_until")
            report["recent_403_events"] = summarize_recent_403_events(proxy_state)
            report["pool_block_active"] = is_future_timestamp(
                proxy_state.get("global_blocked_until")
            )
            self.storage.save_partial(records)
            self.storage.save_validation_report(build_validation_report(records))
            self.storage.save_proxy_progress_report(report)
            self.storage.save_detail_deferrals(deferrals)
            self.storage.save_proxy_state(proxy_state)

            logging.info(
                "Round-robin turn completed for %s: %s attempted, %s succeeded, %s pending.",
                state["proxy_label"],
                result.get("attempted", 0),
                result.get("succeeded", 0),
                pending_after,
            )

            if pending_after == 0:
                if record_limit is None:
                    self.storage.save_final(records)
                    logging.info("All TheFork detail pages have been scraped.")
                else:
                    logging.info(
                        "The configured restaurant limit has no pending TheFork detail records."
                    )
                return records

            if pool_block_triggered and self.stop_on_pool_block:
                logging.warning(
                    "Stopping round-robin mode because the proxy pool reached the "
                    "HTTP 403 threshold. Global cooldown until %s.",
                    proxy_state.get("global_blocked_until"),
                )
                return records

            if self.proxy_turn_jitter_seconds > 0:
                time.sleep(random.uniform(0, self.proxy_turn_jitter_seconds))

        remaining = count_pending_details(records, record_limit)
        logging.warning(
            "Round-robin proxy mode ended with %s pending TheFork detail records.", remaining
        )
        self.storage.save_partial(records)
        self.storage.save_validation_report(build_validation_report(records))
        report["updated_at"] = utc_timestamp()
        report["latest_pending_details"] = remaining
        report["proxy_results"] = [serializable_proxy_state(state) for state in states]
        report["deferred_url_count"] = count_deferred_urls(deferrals)
        report["deferred_urls"] = summarize_deferrals(deferrals)
        report["global_blocked_until"] = proxy_state.get("global_blocked_until")
        report["recent_403_events"] = summarize_recent_403_events(proxy_state)
        report["pool_block_active"] = is_future_timestamp(proxy_state.get("global_blocked_until"))
        self.storage.save_proxy_progress_report(report)
        self.storage.save_detail_deferrals(deferrals)
        self.storage.save_proxy_state(proxy_state)
        if (remaining == 0 and record_limit is None) or self.save_final_incomplete:
            self.storage.save_final(records)
        return records

    def _next_round_robin_proxy_state(self, active_states: list[dict[str, Any]]) -> dict[str, Any]:
        return min(
            active_states,
            key=lambda state: (
                self._proxy_available_monotonic(state),
                state["turns"],
                state["proxy_index"],
            ),
        )

    def _proxy_wait_seconds(self, state: dict[str, Any]) -> float:
        return max(0.0, self._proxy_available_monotonic(state) - time.monotonic())

    def _proxy_available_monotonic(self, state: dict[str, Any]) -> float:
        available_at = 0.0
        if state["last_used_monotonic"] > 0 and self.proxy_min_rest_seconds > 0:
            available_at = state["last_used_monotonic"] + self.proxy_min_rest_seconds
        blocked_until = float(state.get("blocked_until_monotonic") or 0.0)
        return max(available_at, blocked_until)

    def _next_round_robin_record(
        self,
        records: list[RestaurantRecord],
        record_limit: int | None,
        deferrals: dict[str, Any],
        cycle: int,
    ) -> tuple[int, RestaurantRecord] | None:
        first_deferred: tuple[int, RestaurantRecord] | None = None
        for index, record in enumerate(records, start=1):
            if record_limit is not None and index > record_limit:
                break
            if record.detail_scraped:
                continue

            url = record.restaurant_url or f"{record.restaurant_name}|{record.address}|{index}"
            deferral = deferrals.get(url) or {}
            deferred_until = int(deferral.get("deferred_until_cycle") or 0)
            if deferred_until > cycle:
                if first_deferred is None:
                    first_deferred = (index, record)
                continue
            return index, record

        return first_deferred

    def _scrape_proxy_turn(
        self,
        browser_channel: str | None,
        records: list[RestaurantRecord],
        proxy: ProxyConfig | None,
        record_limit: int | None = None,
        deferrals: dict[str, Any] | None = None,
        cycle: int = 0,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "blocked_or_failed_turn": False,
            "records": records,
            "error": None,
            "attempted_urls": [],
            "succeeded_urls": [],
            "failed_urls": [],
            "failure_http_statuses": [],
            "failure_reasons": [],
            "failure_block_markers": [],
            "last_failure_http_status": None,
            "last_failure_reason": None,
        }
        if deferrals is None:
            deferrals = {}
        try:
            with sync_playwright() as playwright:
                launch_options: dict[str, Any] = {
                    "headless": self.headless,
                    "chromium_sandbox": True,
                    "args": []
                    if self.browser_executable_path
                    else ["--disable-blink-features=AutomationControlled"],
                }
                if self.browser_executable_path:
                    launch_options["executable_path"] = self.browser_executable_path
                elif browser_channel is not None:
                    launch_options["channel"] = browser_channel
                if proxy is not None:
                    logging.info("Using proxy for round-robin turn: %s", proxy.safe_label())
                    launch_options["proxy"] = proxy.to_playwright()

                browser = None
                context_options: dict[str, Any] = {
                    "locale": "it-IT",
                    "timezone_id": "Europe/Rome",
                    "viewport": {"width": 1440, "height": 1800},
                    "user_agent": DEFAULT_USER_AGENT,
                    "extra_http_headers": {
                        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
                    },
                }
                if self.user_data_dir is not None:
                    profile_dir = profile_dir_for_proxy(self.user_data_dir, proxy)
                    profile_dir.mkdir(parents=True, exist_ok=True)
                    logging.info("Using persistent browser profile: %s", profile_dir)
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(profile_dir),
                        **launch_options,
                        **context_options,
                    )
                else:
                    browser = playwright.chromium.launch(**launch_options)
                    context = browser.new_context(**context_options)

                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(self.card_timeout_ms)
                page.set_default_navigation_timeout(self.navigation_timeout_ms)
                try:
                    self._warm_up_browser_profile(page)
                    detail_scraper = self._create_detail_scraper()
                    detail_scraped_at = utc_timestamp()
                    processed_in_turn = 0

                    while processed_in_turn < self.restaurants_per_proxy_turn:
                        next_record = self._next_round_robin_record(
                            records, record_limit, deferrals, cycle
                        )
                        if next_record is None:
                            break
                        index, record = next_record
                        if processed_in_turn >= self.restaurants_per_proxy_turn:
                            break

                        logging.info(
                            "Round-robin detail attempt with %s: record %s/%s %s",
                            proxy.safe_label() if proxy else "direct_ip",
                            index,
                            record_limit or len(records),
                            record.restaurant_url,
                        )
                        enriched_record = detail_scraper.enrich_record(
                            page, record, detail_scraped_at
                        )
                        records[index - 1] = enriched_record
                        result["attempted"] += 1
                        result["attempted_urls"].append(record.restaurant_url)
                        processed_in_turn += 1

                        if enriched_record.detail_scraped:
                            result["succeeded"] += 1
                            result["succeeded_urls"].append(enriched_record.restaurant_url)
                            clear_detail_deferral(deferrals, enriched_record.restaurant_url)
                        else:
                            result["failed"] += 1
                            result["failed_urls"].append(record.restaurant_url)
                            result["blocked_or_failed_turn"] = True
                            result["last_failure_http_status"] = detail_scraper.last_http_status
                            result["last_failure_reason"] = detail_scraper.last_failure_reason
                            if detail_scraper.last_http_status is not None:
                                result["failure_http_statuses"].append(
                                    {
                                        "url": record.restaurant_url,
                                        "status": detail_scraper.last_http_status,
                                    }
                                )
                            if detail_scraper.last_failure_reason:
                                reason_payload = {
                                    "url": record.restaurant_url,
                                    "reason": detail_scraper.last_failure_reason,
                                }
                                if detail_scraper.last_block_marker:
                                    reason_payload["marker"] = detail_scraper.last_block_marker
                                    result["failure_block_markers"].append(
                                        {
                                            "url": record.restaurant_url,
                                            "marker": detail_scraper.last_block_marker,
                                        }
                                    )
                                result["failure_reasons"].append(reason_payload)
                            register_detail_deferral(
                                deferrals=deferrals,
                                record=record,
                                record_index=index,
                                cycle=cycle,
                                max_failures=self.max_url_failures_before_deferral,
                                retry_cycles=self.deferred_url_retry_cycles,
                                http_status=detail_scraper.last_http_status,
                                reason=detail_scraper.last_failure_reason,
                                force_defer=is_detail_block_failure(
                                    detail_scraper.last_http_status,
                                    detail_scraper.last_failure_reason,
                                ),
                            )
                            break

                        if processed_in_turn < self.restaurants_per_proxy_turn:
                            self._wait_between_detail_pages(page)

                    result["records"] = records
                    if result["attempted"] > 0 and result["succeeded"] == 0:
                        result["blocked_or_failed_turn"] = True
                    return result
                finally:
                    context.close()
                    if browser is not None:
                        browser.close()
        except (PlaywrightError, PlaywrightTimeoutError) as error:
            result["failed"] += 1
            result["blocked_or_failed_turn"] = True
            result["error"] = str(error)
            result["last_failure_reason"] = type(error).__name__
            logging.warning(
                "Round-robin proxy turn failed before completing a detail record with %s: %s",
                proxy.safe_label() if proxy else "direct_ip",
                error,
            )
            return result

    def _scrape_detail_batch_with_channel(
        self,
        browser_channel: str | None,
        records: list[RestaurantRecord],
    ) -> list[RestaurantRecord]:
        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {
                "headless": self.headless,
                "chromium_sandbox": True,
                "args": []
                if self.browser_executable_path
                else ["--disable-blink-features=AutomationControlled"],
            }
            if self.browser_executable_path:
                launch_options["executable_path"] = self.browser_executable_path
            elif browser_channel is not None:
                launch_options["channel"] = browser_channel
            self.detail_batch_counter += 1
            proxy = proxy_for_batch(self.proxy_configs, self.detail_batch_counter)
            if proxy is not None:
                logging.info(
                    "Using proxy for detail batch %s: %s",
                    self.detail_batch_counter,
                    proxy.safe_label(),
                )
                launch_options["proxy"] = proxy.to_playwright()

            browser = None
            context_options: dict[str, Any] = {
                "locale": "it-IT",
                "timezone_id": "Europe/Rome",
                "viewport": {"width": 1440, "height": 1800},
                "user_agent": DEFAULT_USER_AGENT,
                "extra_http_headers": {"Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"},
            }
            if self.user_data_dir is not None:
                profile_dir = profile_dir_for_proxy(self.user_data_dir, proxy)
                profile_dir.mkdir(parents=True, exist_ok=True)
                logging.info("Using persistent browser profile: %s", profile_dir)
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    **launch_options,
                    **context_options,
                )
            else:
                browser = playwright.chromium.launch(**launch_options)
                context = browser.new_context(**context_options)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(self.card_timeout_ms)
            page.set_default_navigation_timeout(self.navigation_timeout_ms)
            try:
                self._warm_up_browser_profile(page)
                return self._scrape_detail_pages(
                    page, records, max_detail_records=self.detail_batch_size
                )
            finally:
                context.close()
                if browser is not None:
                    browser.close()

    def _scrape_detail_pages(
        self,
        page: Page,
        records: list[RestaurantRecord],
        max_detail_records: int | None = None,
    ) -> list[RestaurantRecord]:
        detail_scraper = self._create_detail_scraper()
        detail_scraped_at = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        total_records = len(records)
        consecutive_failures = 0
        processed_missing_records = 0
        pending_indexes = [
            index for index, record in enumerate(records, start=1) if not record.detail_scraped
        ]
        shard_pending_indexes = [
            record_index
            for pending_position, record_index in enumerate(pending_indexes, start=1)
            if self._pending_position_belongs_to_shard(pending_position)
        ]

        for index in shard_pending_indexes:
            record = records[index - 1]
            if max_detail_records is not None and processed_missing_records >= max_detail_records:
                logging.info("Reached configured detail batch size: %s", max_detail_records)
                break

            logging.info(
                "Scraping TheFork detail page %s/%s: %s",
                index,
                total_records,
                record.restaurant_url,
            )
            enriched_record = detail_scraper.enrich_record(page, record, detail_scraped_at)
            records[index - 1] = enriched_record
            processed_missing_records += 1

            if enriched_record.detail_scraped:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logging.warning(
                    "TheFork detail page failed. Consecutive detail failures: %s/%s",
                    consecutive_failures,
                    self.max_consecutive_detail_failures,
                )

            if index == 1 or index % self.partial_every_restaurants == 0:
                self.storage.save_partial(records)

            if consecutive_failures >= self.max_consecutive_detail_failures:
                self.detail_stopped_early = True
                logging.warning(
                    "Stopping detail scraping after %s consecutive failures. "
                    "Partial output was kept so the run can be resumed later.",
                    consecutive_failures,
                )
                self.storage.save_partial(records)
                break

            if index < total_records:
                self._wait_between_detail_pages(page)

        return records

    def _pending_position_belongs_to_shard(self, pending_position: int) -> bool:
        return ((pending_position - 1) % self.detail_shard_count) + 1 == self.detail_shard_index

    def _create_detail_scraper(self) -> TheForkDetailScraper:
        return TheForkDetailScraper(
            max_reviews_per_restaurant=self.max_reviews_per_restaurant,
            navigation_timeout_ms=self.navigation_timeout_ms,
            detail_timeout_ms=self.card_timeout_ms,
            human_scroll_enabled=self.human_scroll_enabled,
            pause_on_block=self.pause_on_antibot,
            micro_pause_min_ms=self.micro_pause_min_ms,
            micro_pause_max_ms=self.micro_pause_max_ms,
        )

    def _detail_delay_for_next_page(self) -> float:
        if self.detail_delay_min_seconds is None and self.detail_delay_max_seconds is None:
            return max(0.0, self.detail_delay_seconds)

        min_delay = self.detail_delay_min_seconds
        max_delay = self.detail_delay_max_seconds
        if min_delay is None:
            min_delay = self.detail_delay_seconds
        if max_delay is None:
            max_delay = min_delay

        min_delay = max(0.0, min_delay)
        max_delay = max(min_delay, max_delay)
        return random.uniform(min_delay, max_delay)

    def _wait_between_detail_pages(self, page: Page) -> None:
        delay_seconds = self._detail_delay_for_next_page()
        if delay_seconds <= 0:
            return
        page.wait_for_timeout(int(delay_seconds * 1000))

    def _detect_max_page(self, page: Page, page_card_count: int) -> int | None:
        pagination_max_page = self._detect_pagination_max_page(page)
        total_count = self._detect_total_restaurant_count(page)
        total_max_page = None
        if total_count and page_card_count > 0:
            total_max_page = math.ceil(total_count / page_card_count)

        candidates = [candidate for candidate in (pagination_max_page, total_max_page) if candidate]
        if not candidates:
            return None

        detected_max_page = max(candidates)
        logging.info("Detected approximately %s listing pages.", detected_max_page)
        return detected_max_page

    def _detect_pagination_max_page(self, page: Page) -> int | None:
        try:
            page_numbers = page.evaluate(
                """
                () => {
                  const clean = (value) => (value || '').trim().replace(/\\s+/g, ' ');
                  const numbers = [];
                  const controls = Array.from(document.querySelectorAll(
                    'button[aria-label*="Pagina" i], a[aria-label*="Pagina" i], a[href*="p="]'
                  ));

                  for (const control of controls) {
                    let node = control;
                    for (let depth = 0; node && depth < 5; depth += 1, node = node.parentElement) {
                      const localNumbers = [];
                      for (const element of Array.from(node.querySelectorAll('a, button'))) {
                        const text = clean(element.innerText || element.textContent || '');
                        if (/^\\d+$/.test(text)) {
                          localNumbers.push(Number(text));
                        }
                        const href = element.href || '';
                        const match = href.match(/[?&]p=(\\d+)/);
                        if (match) {
                          localNumbers.push(Number(match[1]));
                        }
                      }
                      const pageNumbers = localNumbers.filter(
                        (number) => number > 0 && number <= 500
                      );
                      if (pageNumbers.length >= 2) {
                        numbers.push(...pageNumbers);
                      }
                    }
                  }
                  return Array.from(new Set(numbers)).filter((number) => number > 0);
                }
                """
            )
        except PlaywrightError:
            return None

        return max(page_numbers) if page_numbers else None

    def _detect_total_restaurant_count(self, page: Page) -> int | None:
        try:
            page_texts = page.evaluate(
                """
                () => [
                  ((document.querySelector('main') || document.body).innerText || '')
                    .slice(0, 2500),
                  (document.body.innerText || '').slice(0, 3500),
                ]
                """
            )
        except PlaywrightError:
            return None

        for page_text in page_texts:
            matches = re.findall(r"\b(\d[\d.\s]*)\s+ristoranti\b", page_text, re.IGNORECASE)
            for match in matches:
                total = int(re.sub(r"\D", "", match))
                if 10 < total <= 10_000:
                    return total
        return None


def normalize_browser_channel(browser_channel: str | None) -> str | None:
    if browser_channel is None:
        return None
    normalized_channel = browser_channel.strip().lower()
    if normalized_channel in {"", "auto"}:
        return None
    if normalized_channel in {"chromium", "bundled", "bundled-chromium"}:
        return None
    return normalized_channel


def build_listing_url(start_url: str, page_number: int) -> str:
    parsed_url = urlsplit(start_url)
    query = parse_qs(parsed_url.query, keep_blank_values=True)
    if page_number <= 1:
        query.pop("p", None)
    else:
        query["p"] = [str(page_number)]
    encoded_query = urlencode(query, doseq=True)
    return urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, encoded_query, ""))


def should_save_partial(processed_pages: int, partial_every_pages: int) -> bool:
    return processed_pages == 1 or processed_pages % partial_every_pages == 0


def count_pending_details(records: list[RestaurantRecord], record_limit: int | None = None) -> int:
    scoped_records = records[:record_limit] if record_limit is not None else records
    return sum(1 for record in scoped_records if not record.detail_scraped)


def serializable_proxy_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in state.items()
        if key not in {"proxy", "last_used_monotonic", "blocked_until_monotonic"}
    }


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_timestamp_after(seconds: float) -> str:
    return (
        (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=max(0.0, seconds)))
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_proxy_state(payload: dict[str, Any]) -> dict[str, Any]:
    state = payload if isinstance(payload, dict) else {}
    proxies = state.get("proxies")
    recent_403_events = state.get("recent_403_events")
    return {
        "updated_at": state.get("updated_at") or utc_timestamp(),
        "global_blocked_until": future_timestamp_or_none(state.get("global_blocked_until")),
        "global_blocked_reason": state.get("global_blocked_reason"),
        "recent_403_events": recent_403_events if isinstance(recent_403_events, list) else [],
        "proxies": proxies if isinstance(proxies, dict) else {},
    }


def parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_future_timestamp(value: Any) -> bool:
    parsed = parse_utc_timestamp(value)
    return parsed is not None and parsed > datetime.now(timezone.utc)


def future_timestamp_or_none(value: Any) -> str | None:
    return value if is_future_timestamp(value) else None


def monotonic_deadline_for_timestamp(value: Any) -> float:
    parsed = parse_utc_timestamp(value)
    if parsed is None:
        return 0.0
    seconds = (parsed - datetime.now(timezone.utc)).total_seconds()
    if seconds <= 0:
        return 0.0
    return time.monotonic() + seconds


def last_item(items: Any) -> Any:
    if isinstance(items, list) and items:
        return items[-1]
    return None


def proxy_state_entry(proxy_state: dict[str, Any], proxy_label: str) -> dict[str, Any]:
    proxies = proxy_state.setdefault("proxies", {})
    entry = proxies.get(proxy_label)
    if not isinstance(entry, dict):
        entry = {"proxy_label": proxy_label}
        proxies[proxy_label] = entry
    return entry


def record_proxy_success(proxy_state: dict[str, Any], proxy_label: str, url: str | None) -> None:
    entry = proxy_state_entry(proxy_state, proxy_label)
    entry["last_success_at"] = utc_timestamp()
    entry["last_success_url"] = url
    proxy_state["updated_at"] = utc_timestamp()


def record_proxy_failure(
    proxy_state: dict[str, Any],
    proxy_label: str,
    url: str | None,
    reason: str | None,
    http_status: int | None,
) -> None:
    entry = proxy_state_entry(proxy_state, proxy_label)
    entry["last_failure_at"] = utc_timestamp()
    entry["last_failure_url"] = url
    entry["last_failure_reason"] = reason
    entry["last_http_status"] = http_status
    proxy_state["updated_at"] = utc_timestamp()


def set_proxy_blocked_until(
    proxy_state: dict[str, Any], proxy_label: str, blocked_until: str | None
) -> None:
    if not blocked_until:
        return
    entry = proxy_state_entry(proxy_state, proxy_label)
    current_until = parse_utc_timestamp(entry.get("blocked_until"))
    next_until = parse_utc_timestamp(blocked_until)
    if next_until is not None and (current_until is None or next_until > current_until):
        entry["blocked_until"] = blocked_until
    proxy_state["updated_at"] = utc_timestamp()


def is_detail_block_failure(http_status: int | None, reason: str | None) -> bool:
    return http_status == 403 or reason == "blocked_page"


def record_proxy_403_event(
    proxy_state: dict[str, Any],
    proxy_label: str,
    url: str | None,
    reason: str | None,
    http_status: int | None,
    window_seconds: float,
    threshold: int,
    cooldown_seconds: float,
) -> bool:
    entry = proxy_state_entry(proxy_state, proxy_label)
    if http_status == 403:
        entry["http_403_count"] = int(entry.get("http_403_count") or 0) + 1
        entry["last_http_403_at"] = utc_timestamp()
        entry["last_http_403_url"] = url
    entry["block_count"] = int(entry.get("block_count") or 0) + 1
    entry["last_block_at"] = utc_timestamp()
    entry["last_block_url"] = url
    entry["last_block_reason"] = reason

    event = {
        "proxy_label": proxy_label,
        "url": url,
        "reason": reason,
        "http_status": http_status,
        "created_at": utc_timestamp(),
    }
    recent_events = prune_recent_403_events(
        [*proxy_state.get("recent_403_events", []), event], window_seconds
    )
    proxy_state["recent_403_events"] = recent_events
    proxy_state["updated_at"] = utc_timestamp()

    distinct_proxy_labels = {
        item.get("proxy_label") for item in recent_events if item.get("proxy_label")
    }
    if len(distinct_proxy_labels) < threshold:
        return False

    blocked_until = utc_timestamp_after(cooldown_seconds)
    existing_until = parse_utc_timestamp(proxy_state.get("global_blocked_until"))
    next_until = parse_utc_timestamp(blocked_until)
    if next_until is not None and (existing_until is None or next_until > existing_until):
        proxy_state["global_blocked_until"] = blocked_until
        proxy_state["global_blocked_reason"] = (
            f"{len(distinct_proxy_labels)} distinct proxies returned HTTP 403 or a block page "
            f"within {int(window_seconds)} seconds"
        )
        proxy_state["updated_at"] = utc_timestamp()
    return True


def prune_recent_403_events(events: list[Any], window_seconds: float) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(1.0, window_seconds))
    kept: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        created_at = parse_utc_timestamp(event.get("created_at"))
        if created_at is None or created_at < cutoff:
            continue
        kept.append(
            {
                "proxy_label": event.get("proxy_label"),
                "url": event.get("url"),
                "reason": event.get("reason"),
                "http_status": event.get("http_status"),
                "created_at": event.get("created_at"),
            }
        )
    return kept[-100:]


def summarize_recent_403_events(
    proxy_state: dict[str, Any], limit: int = 30
) -> list[dict[str, Any]]:
    events = proxy_state.get("recent_403_events")
    if not isinstance(events, list):
        return []
    return [
        {
            "proxy_label": event.get("proxy_label"),
            "url": event.get("url"),
            "reason": event.get("reason"),
            "http_status": event.get("http_status"),
            "created_at": event.get("created_at"),
        }
        for event in events[-limit:]
        if isinstance(event, dict)
    ]


def register_detail_deferral(
    deferrals: dict[str, Any],
    record: RestaurantRecord,
    record_index: int,
    cycle: int,
    max_failures: int,
    retry_cycles: int,
    http_status: int | None = None,
    reason: str | None = None,
    force_defer: bool = False,
) -> None:
    url = record.restaurant_url or f"{record.restaurant_name}|{record.address}|{record_index}"
    if not url:
        return

    item = deferrals.get(url, {})
    failures = int(item.get("failures") or 0) + 1
    item.update(
        {
            "url": url,
            "restaurant_name": record.restaurant_name,
            "record_index": record_index,
            "failures": failures,
            "last_failed_at": utc_timestamp(),
            "last_failed_cycle": cycle,
            "last_http_status": http_status,
            "last_reason": reason,
        }
    )
    if force_defer or failures >= max_failures:
        item["deferred_until_cycle"] = cycle + retry_cycles
        item["deferred"] = True
        logging.warning(
            "Deferring detail URL after %s failed attempts until round-robin cycle %s: %s",
            failures,
            item["deferred_until_cycle"],
            url,
        )
    deferrals[url] = item


def clear_detail_deferral(deferrals: dict[str, Any], url: str | None) -> None:
    if not url:
        return
    if url in deferrals:
        del deferrals[url]


def restore_deferred_urls(deferrals: dict[str, Any], max_failures: int, retry_cycles: int) -> int:
    restored = 0
    for item in deferrals.values():
        failures = int(item.get("failures") or 0)
        deferred_until = int(item.get("deferred_until_cycle") or 0)
        if failures >= max_failures and deferred_until <= 0:
            item["deferred_until_cycle"] = retry_cycles
            item["deferred"] = True
            restored += 1
    return restored


def count_deferred_urls(deferrals: dict[str, Any]) -> int:
    return sum(1 for item in deferrals.values() if item.get("deferred"))


def summarize_deferrals(deferrals: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
    items = sorted(
        deferrals.values(),
        key=lambda item: (
            int(item.get("deferred_until_cycle") or 0),
            -(int(item.get("failures") or 0)),
        ),
    )
    return [
        {
            "url": item.get("url"),
            "restaurant_name": item.get("restaurant_name"),
            "record_index": item.get("record_index"),
            "failures": item.get("failures"),
            "deferred_until_cycle": item.get("deferred_until_cycle"),
            "last_failed_at": item.get("last_failed_at"),
            "last_http_status": item.get("last_http_status"),
            "last_reason": item.get("last_reason"),
        }
        for item in items[:limit]
    ]


def profile_dir_for_proxy(base_dir: Path, proxy: ProxyConfig | None) -> Path:
    if proxy is None:
        return base_dir
    return base_dir.parent / "browser_profiles" / proxy.safe_label()


def create_default_storage(
    project_root: Path,
    output_dir: str | None = None,
    input_partial_path: str | None = None,
) -> JsonStorage:
    input_path = None
    if input_partial_path is not None:
        input_path = Path(input_partial_path)
        if not input_path.is_absolute():
            input_path = project_root / input_path
    if output_dir is None:
        return JsonStorage(project_root / "data/raw/thefork", input_path)
    output_path = Path(output_dir)
    if output_path.is_absolute():
        return JsonStorage(output_path, input_path)
    return JsonStorage(project_root / output_path, input_path)
