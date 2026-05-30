from __future__ import annotations

import logging
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from . import config
from .detail_scraper import TripadvisorDetailScraper
from .models import RestaurantRecord
from .parser import deduplication_key, parse_restaurant_card
from .storage import JsonStorage
from .validators import build_validation_report


START_URL = config.START_URL
TRIPADVISOR_BASE_URL = "https://www.tripadvisor.it"
RESTAURANT_LINK_SELECTOR = 'a[href*="Restaurant_Review-"]'
RESTAURANT_HREF_PATTERN = re.compile(
    r"Restaurant_Review-g187849-d\d+-Reviews-",
    re.IGNORECASE,
)
DEFAULT_BROWSER_CHANNELS: tuple[str | None, ...] = ("chrome", "msedge", None)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class AccessBlockedError(RuntimeError):
    pass


class TripadvisorScraper:
    def __init__(
        self,
        storage: JsonStorage,
        start_url: str = START_URL,
        browser_channel: str | None = None,
        headless: bool = True,
        delay_seconds: float = 1.5,
        partial_every_pages: int = 5,
        partial_every_restaurants: int = config.SAVE_PARTIAL_EVERY_N_RESTAURANTS,
        max_empty_pages: int = 3,
        navigation_timeout_ms: int = 60_000,
        card_timeout_ms: int = 30_000,
        scrape_detail_pages: bool = config.SCRAPE_DETAIL_PAGES,
        detail_delay_seconds: float = config.DELAY_BETWEEN_DETAIL_PAGES_SECONDS,
        max_reviews_per_restaurant: int = config.MAX_REVIEWS_PER_RESTAURANT,
        user_data_dir: Path | None = None,
        manual_unlock: bool = False,
        unlock_timeout_seconds: int = 300,
        save_session_only: bool = False,
        resume: bool = False,
        max_consecutive_detail_failures: int = 10,
        auto_detail_until_complete: bool = False,
        detail_batch_size: int = config.DETAIL_BATCH_SIZE,
        cooldown_seconds: int = config.COOLDOWN_SECONDS,
        max_cooldown_seconds: int = config.MAX_COOLDOWN_SECONDS,
        cooldown_multiplier: float = config.COOLDOWN_MULTIPLIER,
        max_auto_detail_cycles: int = config.MAX_AUTO_DETAIL_CYCLES,
        save_final_incomplete: bool = False,
    ) -> None:
        self.storage = storage
        self.start_url = start_url
        self.browser_channel = normalize_browser_channel(browser_channel)
        self.headless = headless
        self.delay_seconds = delay_seconds
        self.partial_every_pages = max(1, partial_every_pages)
        self.partial_every_restaurants = max(1, partial_every_restaurants)
        self.max_empty_pages = max(1, max_empty_pages)
        self.navigation_timeout_ms = navigation_timeout_ms
        self.card_timeout_ms = card_timeout_ms
        self.scrape_detail_pages = scrape_detail_pages
        self.detail_delay_seconds = detail_delay_seconds
        self.max_reviews_per_restaurant = max_reviews_per_restaurant
        self.user_data_dir = user_data_dir
        self.manual_unlock = manual_unlock
        self.unlock_timeout_seconds = max(1, unlock_timeout_seconds)
        self.save_session_only = save_session_only
        self.resume = resume
        self.max_consecutive_detail_failures = max(1, max_consecutive_detail_failures)
        self.auto_detail_until_complete = auto_detail_until_complete
        self.detail_batch_size = max(1, detail_batch_size)
        self.cooldown_seconds = max(0, cooldown_seconds)
        self.max_cooldown_seconds = max(self.cooldown_seconds, max_cooldown_seconds)
        self.cooldown_multiplier = max(1.0, cooldown_multiplier)
        self.max_auto_detail_cycles = max(1, max_auto_detail_cycles)
        self.save_final_incomplete = save_final_incomplete
        self.detail_stopped_early = False

    def scrape(self, max_pages: int | None = None, max_restaurants: int | None = None) -> list[RestaurantRecord]:
        if self.auto_detail_until_complete:
            return self._auto_detail_until_complete(max_pages=max_pages, max_restaurants=max_restaurants)

        channels = self._candidate_channels()
        last_error: Exception | None = None

        for channel in channels:
            channel_name = channel or "bundled chromium"
            logging.info("Starting scraper with browser channel: %s", channel_name)
            try:
                return self._scrape_with_channel(channel, max_pages, max_restaurants)
            except AccessBlockedError as error:
                last_error = error
                logging.warning("%s was blocked or returned no listing content: %s", channel_name, error)
            except PlaywrightError as error:
                last_error = error
                logging.warning("Could not use browser channel %s: %s", channel_name, error)

        raise RuntimeError("The scraper could not load Tripadvisor with any configured browser channel.") from last_error

    def _candidate_channels(self) -> list[str | None]:
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
        starting_page_number = 1
        if self.resume:
            for record in self.storage.load_partial():
                records_by_key[deduplication_key(record)] = record
                starting_page_number = max(starting_page_number, record.source_page_number + 1)
            if records_by_key:
                logging.info(
                    "Resume mode enabled. Continuing from page %s with %s existing records.",
                    starting_page_number,
                    len(records_by_key),
                )
        visited_urls: set[str] = set()
        detected_total_count: int | None = None
        consecutive_empty_pages = 0
        scraped_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {
                "headless": self.headless,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if browser_channel is not None:
                launch_options["channel"] = browser_channel

            if self.manual_unlock and self.headless:
                logging.info("Manual unlock mode requires a visible browser. Running headed.")
                launch_options["headless"] = False

            browser = None
            context_options: dict[str, Any] = {
                "locale": "it-IT",
                "timezone_id": "Europe/Rome",
                "viewport": {"width": 1440, "height": 1800},
                "user_agent": DEFAULT_USER_AGENT,
                "extra_http_headers": {"Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"},
            }
            if self.user_data_dir is not None:
                self.user_data_dir.mkdir(parents=True, exist_ok=True)
                logging.info("Using persistent browser profile: %s", self.user_data_dir)
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.user_data_dir),
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
                page_number = starting_page_number
                processed_pages = 0
                next_url: str | None = build_offset_listing_url(self.start_url, page_number)
                while next_url:
                    if max_pages is not None and processed_pages >= max_pages:
                        logging.info("Reached configured page limit: %s", max_pages)
                        break

                    normalized_next_url = normalize_listing_url(next_url)
                    if normalized_next_url in visited_urls:
                        logging.info("Stopping because listing URL was already visited: %s", normalized_next_url)
                        break
                    visited_urls.add(normalized_next_url)

                    logging.info("Loading listing page %s: %s", page_number, next_url)
                    response_status = self._load_page(page, next_url)
                    if response_status == 403 or self._is_blocked_page(page):
                        if self.manual_unlock:
                            self._wait_for_manual_unlock(page)
                        else:
                            raise AccessBlockedError("Tripadvisor returned a DataDome or captcha block.")

                    self._handle_cookie_popup(page)
                    self._wait_for_cards(page)

                    if self.save_session_only:
                        if self._has_restaurant_links(page):
                            logging.info("Session unlock completed. No JSON output was written.")
                            return []
                        raise AccessBlockedError("Session unlock did not reach a Tripadvisor restaurant listing.")

                    self._scroll_listing(page)

                    card_payloads = self._extract_card_payloads(page)
                    if page_number == 1 and not card_payloads:
                        raise AccessBlockedError("No Tripadvisor restaurant links were found on the first page.")

                    page_records = self._parse_page_records(card_payloads, scraped_at, page_number)
                    new_count = self._merge_records(records_by_key, page_records)
                    processed_pages += 1

                    total_records = len(records_by_key)
                    detected_candidate = self._detect_total_result_count(page)
                    if detected_candidate is not None and detected_candidate >= total_records:
                        detected_total_count = detected_total_count or detected_candidate
                    logging.info(
                        "Page %s parsed: %s cards, %s valid records, %s new records, %s total records",
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
                        logging.warning("Stopping after too many consecutive pages without new restaurants.")
                        break

                    if max_restaurants is not None and total_records >= max_restaurants:
                        logging.info("Reached configured restaurant limit: %s", max_restaurants)
                        break

                    if detected_total_count is not None and total_records >= detected_total_count:
                        logging.info("Reached detected result count: %s", detected_total_count)
                        break

                    next_url = self._detect_next_page_url(page) or build_offset_listing_url(self.start_url, page_number + 1)
                    page_number += 1
                    if self.delay_seconds > 0:
                        time.sleep(self.delay_seconds)

                records = list(records_by_key.values())
                if max_restaurants is not None:
                    records = records[:max_restaurants]

                if self.scrape_detail_pages:
                    records = self._scrape_detail_pages(page, records)

                self.storage.save_partial(records)
                if save_final and (not self.detail_stopped_early or self.save_final_incomplete):
                    self.storage.save_final(records)
                elif self.detail_stopped_early:
                    logging.warning("Final output was not overwritten because detail scraping stopped early.")
                self.storage.save_validation_report(build_validation_report(records))
                return records
            finally:
                context.close()
                if browser is not None:
                    browser.close()

    def _load_page(self, page: Page, page_url: str) -> int | None:
        try:
            response = page.goto(page_url, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms)
            return response.status if response else None
        except PlaywrightTimeoutError:
            logging.warning("Timed out while loading %s", page_url)
            return None

    def _is_blocked_page(self, page: Page) -> bool:
        try:
            html = page.evaluate("() => document.documentElement.outerHTML.slice(0, 10000)")
        except PlaywrightError:
            return False
        block_markers = ("captcha-delivery", "DataDome", "geo.captcha-delivery.com")
        return any(marker in html for marker in block_markers)

    def _wait_for_manual_unlock(self, page: Page, target_selector: str = RESTAURANT_LINK_SELECTOR) -> None:
        logging.warning(
            "Tripadvisor is showing a DataDome or captcha challenge. "
            "Solve the captcha in the browser window; the scraper will continue automatically."
        )
        deadline = time.monotonic() + self.unlock_timeout_seconds
        next_log_time = 0.0

        while time.monotonic() < deadline:
            if self._has_selector(page, target_selector) and not self._is_blocked_page(page):
                logging.info("Manual unlock completed; target page content is visible.")
                return

            now = time.monotonic()
            if now >= next_log_time:
                remaining_seconds = int(deadline - now)
                logging.info("Waiting for manual unlock. Timeout in %s seconds.", remaining_seconds)
                next_log_time = now + 15

            try:
                page.wait_for_timeout(1_000)
            except PlaywrightError:
                time.sleep(1)

        raise AccessBlockedError("Manual unlock timed out before Tripadvisor page content appeared.")

    def _has_restaurant_links(self, page: Page) -> bool:
        try:
            return bool(
                page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll('a[href*="Restaurant_Review-"]'))
                      .some((anchor) => /Restaurant_Review-g187849-d\\d+-Reviews-/i.test(anchor.href || anchor.getAttribute('href') || ''))
                    """
                )
            )
        except PlaywrightError:
            return False

    def _has_selector(self, page: Page, selector: str) -> bool:
        try:
            if selector == RESTAURANT_LINK_SELECTOR:
                return self._has_restaurant_links(page)
            return bool(page.locator(selector).first.count()) and page.locator(selector).first.is_visible(timeout=1_000)
        except PlaywrightError:
            return False

    def _handle_cookie_popup(self, page: Page) -> None:
        button_names = [
            r"^Accetta tutto$",
            r"^Accetta tutti$",
            r"^Accept all$",
            r"^I agree$",
            r"^OK$",
        ]
        for button_name in button_names:
            try:
                button = page.get_by_role("button", name=re.compile(button_name, re.IGNORECASE)).first
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
                      count: document.querySelectorAll('a[href*="Restaurant_Review-"]').length,
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
              const linkSelector = 'a[href*="Restaurant_Review-"]';
              const restaurantPattern = /Restaurant_Review-g187849-d\\d+-Reviews-/i;
              const clean = (value) => (value || '').trim();
              const hasCardSignal = (text) => (
                /\\b[0-5][,.][0-9]\\b/.test(text) ||
                /\\([\\d.,\\s]+\\s+(reviews?|recensioni)\\)/i.test(text) ||
                /\\${1,4}/.test(text) ||
                /\\u20ac{1,4}/.test(text)
              );
              const bestTextForLink = (anchor) => {
                const anchorText = clean(anchor.innerText || anchor.textContent || '');
                if (anchorText.length >= 15 && hasCardSignal(anchorText)) {
                  return anchorText;
                }

                let node = anchor.parentElement;
                for (let depth = 0; node && depth < 7; depth += 1, node = node.parentElement) {
                  const candidateText = clean(node.innerText || '');
                  const restaurantLinkCount = node.querySelectorAll(linkSelector).length;
                  if (
                    candidateText.length >= 25 &&
                    candidateText.length <= 2200 &&
                    restaurantLinkCount <= 6 &&
                    hasCardSignal(candidateText)
                  ) {
                    return candidateText;
                  }
                }
                return anchorText;
              };

              const seen = new Set();
              return Array.from(document.querySelectorAll(linkSelector))
                .filter((anchor) => restaurantPattern.test(anchor.getAttribute('href') || anchor.href || ''))
                .map((anchor) => ({
                  href: anchor.href || anchor.getAttribute('href'),
                  aria_label: anchor.getAttribute('aria-label'),
                  link_text: clean(anchor.innerText || anchor.textContent || ''),
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
                link_text=payload.get("link_text"),
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
        if max_restaurants is not None:
            records = records[:max_restaurants]

        if not records:
            logging.info("No partial output found. Collecting listing data before detail auto-resume.")
            original_scrape_detail_pages = self.scrape_detail_pages
            original_resume = self.resume
            try:
                self.scrape_detail_pages = False
                self.resume = False
                records = self._scrape_with_channel(
                    channel,
                    max_pages=max_pages,
                    max_restaurants=max_restaurants,
                    save_final=False,
                )
            finally:
                self.scrape_detail_pages = original_scrape_detail_pages
                self.resume = original_resume

        cooldown_seconds = self.cooldown_seconds
        previous_remaining = count_pending_details(records)

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
                logging.info("All Tripadvisor detail pages have been scraped.")
                return records

            self.detail_stopped_early = False
            records = self._scrape_detail_batch_with_channel(channel, records)
            self.storage.save_partial(records)
            self.storage.save_validation_report(build_validation_report(records))

            remaining = count_pending_details(records)
            if remaining == 0:
                self.storage.save_final(records)
                logging.info("All Tripadvisor detail pages have been scraped.")
                return records

            made_progress = remaining < previous_remaining
            previous_remaining = remaining
            if self.detail_stopped_early or not made_progress:
                logging.warning(
                    "Tripadvisor detail scraping is blocked or made no progress. "
                    "Cooling down for %s seconds before retrying.",
                    cooldown_seconds,
                )
                if cooldown_seconds > 0:
                    time.sleep(cooldown_seconds)
                cooldown_seconds = min(
                    self.max_cooldown_seconds,
                    int(max(cooldown_seconds + 1, cooldown_seconds * self.cooldown_multiplier)),
                )
            else:
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

    def _scrape_detail_batch_with_channel(
        self,
        browser_channel: str | None,
        records: list[RestaurantRecord],
    ) -> list[RestaurantRecord]:
        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {
                "headless": self.headless,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if browser_channel is not None:
                launch_options["channel"] = browser_channel
            if self.manual_unlock and self.headless:
                logging.info("Manual unlock mode requires a visible browser. Running headed.")
                launch_options["headless"] = False

            browser = None
            context_options: dict[str, Any] = {
                "locale": "it-IT",
                "timezone_id": "Europe/Rome",
                "viewport": {"width": 1440, "height": 1800},
                "user_agent": DEFAULT_USER_AGENT,
                "extra_http_headers": {"Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"},
            }
            if self.user_data_dir is not None:
                self.user_data_dir.mkdir(parents=True, exist_ok=True)
                logging.info("Using persistent browser profile: %s", self.user_data_dir)
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.user_data_dir),
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
                return self._scrape_detail_pages(page, records, max_detail_records=self.detail_batch_size)
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
        detail_scraper = TripadvisorDetailScraper(
            max_reviews_per_restaurant=self.max_reviews_per_restaurant,
            navigation_timeout_ms=self.navigation_timeout_ms,
            detail_timeout_ms=self.card_timeout_ms,
        )
        detail_scraped_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        total_records = len(records)
        consecutive_failures = 0
        processed_missing_records = 0
        unlock_callback = (
            (lambda current_page: self._wait_for_manual_unlock(current_page, target_selector="h1"))
            if self.manual_unlock
            else None
        )

        for index, record in enumerate(records, start=1):
            if record.detail_scraped:
                continue

            if max_detail_records is not None and processed_missing_records >= max_detail_records:
                logging.info("Reached configured detail batch size: %s", max_detail_records)
                break

            logging.info("Scraping Tripadvisor detail page %s/%s: %s", index, total_records, record.restaurant_url)
            try:
                enriched_record = detail_scraper.enrich_record(
                    page,
                    record,
                    detail_scraped_at,
                    blocked_detector=self._is_blocked_page,
                    unlock_callback=unlock_callback,
                )
            except AccessBlockedError as error:
                logging.warning("Tripadvisor detail scraping stopped by access block: %s", error)
                self.detail_stopped_early = True
                self.storage.save_partial(records)
                break

            records[index - 1] = enriched_record
            processed_missing_records += 1

            if enriched_record.detail_scraped:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logging.warning(
                    "Tripadvisor detail page failed. Consecutive detail failures: %s/%s",
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

            if self.detail_delay_seconds > 0 and index < total_records:
                time.sleep(self.detail_delay_seconds)

        return records

    def _detect_next_page_url(self, page: Page) -> str | None:
        try:
            next_href = page.evaluate(
                """
                () => {
                  const selectors = [
                    'a[aria-label*="Next" i]',
                    'a[aria-label*="Successiv" i]',
                    'a[rel="next"]'
                  ];
                  for (const selector of selectors) {
                    const element = document.querySelector(selector);
                    if (element && element.href) {
                      return element.href;
                    }
                  }

                  const links = Array.from(document.querySelectorAll('a[href*="Restaurants-g187849"]'));
                  for (const link of links) {
                    const text = (link.innerText || link.textContent || '').trim();
                    const aria = link.getAttribute('aria-label') || '';
                    if (/next|successiv|avanti/i.test(text + ' ' + aria) && link.href) {
                      return link.href;
                    }
                  }
                  return null;
                }
                """
            )
        except PlaywrightError:
            return None
        return next_href

    def _detect_total_result_count(self, page: Page) -> int | None:
        try:
            page_text = page.evaluate(
                """
                () => ((document.querySelector('main') || document.body).innerText || '').slice(0, 5000)
                """
            )
        except PlaywrightError:
            return None

        patterns = [
            r"(?:of|su)\s+([\d.,\s]+)",
            r"([\d.,\s]+)\s+(?:ristoranti|restaurants)",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, page_text, re.IGNORECASE):
                digits = re.sub(r"\D", "", match)
                if not digits:
                    continue
                total = int(digits)
                if total >= 30:
                    logging.info("Detected approximately %s Tripadvisor results.", total)
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


def normalize_listing_url(listing_url: str) -> str:
    parsed_url = urlsplit(listing_url)
    return urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", ""))


def build_offset_listing_url(start_url: str, page_number: int) -> str | None:
    if page_number <= 1:
        return start_url

    offset = (page_number - 1) * 30
    parsed_url = urlsplit(start_url)
    path = parsed_url.path
    path = re.sub(r"-oa\d+", "", path, flags=re.IGNORECASE)
    path = re.sub(
        r"(Restaurants-g187849)(?=-)",
        rf"\1-oa{offset}",
        path,
        count=1,
        flags=re.IGNORECASE,
    )
    return urlunsplit((parsed_url.scheme, parsed_url.netloc, path, "", ""))


def should_save_partial(processed_pages: int, partial_every_pages: int) -> bool:
    return processed_pages == 1 or processed_pages % partial_every_pages == 0


def count_pending_details(records: list[RestaurantRecord]) -> int:
    return sum(1 for record in records if not record.detail_scraped)


def create_default_storage(project_root: Path, output_dir: str | None = None) -> JsonStorage:
    if output_dir is None:
        return JsonStorage(project_root / "output")
    output_path = Path(output_dir)
    if output_path.is_absolute():
        return JsonStorage(output_path)
    return JsonStorage(project_root / output_path)
