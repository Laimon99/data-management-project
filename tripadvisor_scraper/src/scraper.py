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

from .models import RestaurantRecord
from .parser import deduplication_key, parse_restaurant_card
from .storage import JsonStorage


START_URL = "https://www.tripadvisor.it/Restaurants-g187849-Milan_Lombardy.html"
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
        max_empty_pages: int = 3,
        navigation_timeout_ms: int = 60_000,
        card_timeout_ms: int = 30_000,
        user_data_dir: Path | None = None,
        manual_unlock: bool = False,
        unlock_timeout_seconds: int = 300,
        save_session_only: bool = False,
        resume: bool = False,
    ) -> None:
        self.storage = storage
        self.start_url = start_url
        self.browser_channel = normalize_browser_channel(browser_channel)
        self.headless = headless
        self.delay_seconds = delay_seconds
        self.partial_every_pages = max(1, partial_every_pages)
        self.max_empty_pages = max(1, max_empty_pages)
        self.navigation_timeout_ms = navigation_timeout_ms
        self.card_timeout_ms = card_timeout_ms
        self.user_data_dir = user_data_dir
        self.manual_unlock = manual_unlock
        self.unlock_timeout_seconds = max(1, unlock_timeout_seconds)
        self.save_session_only = save_session_only
        self.resume = resume

    def scrape(self, max_pages: int | None = None) -> list[RestaurantRecord]:
        channels = self._candidate_channels()
        last_error: Exception | None = None

        for channel in channels:
            channel_name = channel or "bundled chromium"
            logging.info("Starting scraper with browser channel: %s", channel_name)
            try:
                return self._scrape_with_channel(channel, max_pages)
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

                    if detected_total_count is not None and total_records >= detected_total_count:
                        logging.info("Reached detected result count: %s", detected_total_count)
                        break

                    next_url = self._detect_next_page_url(page) or build_offset_listing_url(self.start_url, page_number + 1)
                    page_number += 1
                    if self.delay_seconds > 0:
                        time.sleep(self.delay_seconds)

                records = list(records_by_key.values())
                self.storage.save_partial(records)
                self.storage.save_final(records)
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

    def _wait_for_manual_unlock(self, page: Page) -> None:
        logging.warning(
            "Tripadvisor is showing a DataDome or captcha challenge. "
            "Solve the captcha in the browser window; the scraper will continue automatically."
        )
        deadline = time.monotonic() + self.unlock_timeout_seconds
        next_log_time = 0.0

        while time.monotonic() < deadline:
            if self._has_restaurant_links(page) and not self._is_blocked_page(page):
                logging.info("Manual unlock completed; restaurant links are visible.")
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

        raise AccessBlockedError("Manual unlock timed out before Tripadvisor restaurant links appeared.")

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


def create_default_storage(project_root: Path) -> JsonStorage:
    return JsonStorage(project_root / "output")
