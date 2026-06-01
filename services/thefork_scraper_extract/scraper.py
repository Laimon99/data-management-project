from __future__ import annotations

import logging
import math
import re
import time
from datetime import datetime, timezone
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
        resume_detail: bool = False,
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
        self.resume_detail = resume_detail
        self.max_consecutive_detail_failures = max(1, max_consecutive_detail_failures)
        self.auto_detail_until_complete = auto_detail_until_complete
        self.detail_batch_size = max(1, detail_batch_size)
        self.cooldown_seconds = max(0, cooldown_seconds)
        self.max_cooldown_seconds = max(self.cooldown_seconds, max_cooldown_seconds)
        self.cooldown_multiplier = max(1.0, cooldown_multiplier)
        self.max_auto_detail_cycles = max(1, max_auto_detail_cycles)
        self.save_final_incomplete = save_final_incomplete
        self.detail_stopped_early = False

    def scrape(
        self, max_pages: int | None = None, max_restaurants: int | None = None
    ) -> list[RestaurantRecord]:
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
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if browser_channel is not None:
                launch_options["channel"] = browser_channel

            browser = playwright.chromium.launch(**launch_options)
            context = browser.new_context(
                locale="it-IT",
                timezone_id="Europe/Rome",
                viewport={"width": 1440, "height": 1800},
                user_agent=DEFAULT_USER_AGENT,
                extra_http_headers={"Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"},
            )
            page = context.new_page()
            page.set_default_timeout(self.card_timeout_ms)
            page.set_default_navigation_timeout(self.navigation_timeout_ms)

            try:
                if self.resume_detail:
                    records = self.storage.load_partial()
                    if max_restaurants is not None:
                        records = records[:max_restaurants]
                    if not records:
                        raise RuntimeError(
                            "Cannot resume detail scraping because the partial output is "
                            "missing or empty."
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
                        "Page %s parsed: %s cards, %s valid records, %s new records, "
                        "%s total records",
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
        if max_restaurants is not None:
            records = records[:max_restaurants]

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

            browser = playwright.chromium.launch(**launch_options)
            context = browser.new_context(
                locale="it-IT",
                timezone_id="Europe/Rome",
                viewport={"width": 1440, "height": 1800},
                user_agent=DEFAULT_USER_AGENT,
                extra_http_headers={"Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"},
            )
            page = context.new_page()
            page.set_default_timeout(self.card_timeout_ms)
            page.set_default_navigation_timeout(self.navigation_timeout_ms)
            try:
                return self._scrape_detail_pages(
                    page, records, max_detail_records=self.detail_batch_size
                )
            finally:
                context.close()
                browser.close()

    def _scrape_detail_pages(
        self,
        page: Page,
        records: list[RestaurantRecord],
        max_detail_records: int | None = None,
    ) -> list[RestaurantRecord]:
        detail_scraper = TheForkDetailScraper(
            max_reviews_per_restaurant=self.max_reviews_per_restaurant,
            navigation_timeout_ms=self.navigation_timeout_ms,
            detail_timeout_ms=self.card_timeout_ms,
        )
        detail_scraped_at = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
        total_records = len(records)
        consecutive_failures = 0
        processed_missing_records = 0

        for index, record in enumerate(records, start=1):
            if record.detail_scraped:
                continue

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

            if self.detail_delay_seconds > 0 and index < total_records:
                time.sleep(self.detail_delay_seconds)

        return records

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
                  (
                    (document.querySelector('main') || document.body).innerText || ''
                  ).slice(0, 2500),
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


def count_pending_details(records: list[RestaurantRecord]) -> int:
    return sum(1 for record in records if not record.detail_scraped)


def create_default_storage(project_root: Path, output_dir: str | None = None) -> JsonStorage:
    if output_dir is None:
        return JsonStorage(project_root / "output")
    output_path = Path(output_dir)
    if output_path.is_absolute():
        return JsonStorage(output_path)
    return JsonStorage(project_root / output_path)
