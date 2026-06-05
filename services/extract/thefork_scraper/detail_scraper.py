from __future__ import annotations

import json
import logging
import random
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .models import RestaurantRecord
from .parser import (
    clean_spaces,
    extract_price_range,
    extract_review_count,
    extract_source_id,
    normalize_restaurant_url,
    split_visible_lines,
)

THEFORK_HOST = "www.thefork.it"
MAX_SCRIPT_CHARS = 300_000
PHONE_PATTERN = re.compile(r"(?:\+39\s*)?(?:0\d{1,3}[\s./-]?\d{5,8}|3\d{2}[\s./-]?\d{6,7})")
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
COORDINATE_PAIR_PATTERNS = [
    re.compile(r"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)"),
    re.compile(r"[?&](?:q|ll)=(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)"),
]
REVIEW_COUNT_TEXT_PATTERN = re.compile(r"([\d.,\s]+)\s+(?:recensioni|reviews?)", re.IGNORECASE)
PRICE_TEXT_PATTERN = re.compile(
    r"(?:Prezzo\s+medio|Average\s+price)\s*(?:EUR|\u20ac)?\s*([\d.,]+\s*(?:\u20ac|EUR)?)",
    re.IGNORECASE,
)
DISCOUNT_TEXT_PATTERN = re.compile(
    r"\b(?:Scont[io]|discount|off)\b[^\n]{0,80}\d+\s*%", re.IGNORECASE
)
SLIDE_COUNT_PATTERN = re.compile(r"Slide\s+\d+\s+di\s+(\d+)", re.IGNORECASE)
BLOCK_MARKERS = (
    "403 forbidden",
    "access denied",
    "forbidden",
    "accesso \u00e8 temporaneamente limitato",
    "captcha",
    "recaptcha",
    "please verify you are a human",
    "datadome",
    "geo.captcha-delivery.com",
)


class TheForkDetailScraper:
    def __init__(
        self,
        max_reviews_per_restaurant: int = 5,
        navigation_timeout_ms: int = 60_000,
        detail_timeout_ms: int = 30_000,
        max_block_retries: int = 1,
        block_retry_delay_ms: int = 5_000,
        human_scroll_enabled: bool = False,
        human_scroll_min_steps: int = 2,
        human_scroll_max_steps: int = 4,
        pause_on_block: bool = False,
        micro_pause_min_ms: int = 0,
        micro_pause_max_ms: int = 0,
    ) -> None:
        self.max_reviews_per_restaurant = max(0, max_reviews_per_restaurant)
        self.navigation_timeout_ms = navigation_timeout_ms
        self.detail_timeout_ms = detail_timeout_ms
        self.max_block_retries = max(0, max_block_retries)
        self.block_retry_delay_ms = max(0, block_retry_delay_ms)
        self.human_scroll_enabled = human_scroll_enabled
        self.human_scroll_min_steps = max(1, human_scroll_min_steps)
        self.human_scroll_max_steps = max(self.human_scroll_min_steps, human_scroll_max_steps)
        self.pause_on_block = pause_on_block
        self.micro_pause_min_ms = max(0, micro_pause_min_ms)
        self.micro_pause_max_ms = max(self.micro_pause_min_ms, micro_pause_max_ms)
        self.last_http_status: int | None = None
        self.last_failure_reason: str | None = None
        self.last_block_marker: str | None = None

    def enrich_record(
        self, page: Page, record: RestaurantRecord, scraped_at: str
    ) -> RestaurantRecord:
        self.last_http_status = None
        self.last_failure_reason = None
        self.last_block_marker = None

        if not record.restaurant_url:
            record.detail_scraped = False
            record.scraped_at = scraped_at
            self.last_failure_reason = "missing_restaurant_url"
            return record

        try:
            status = self._load_detail_page_with_retries(page, record.restaurant_url)
            if status and status >= 400:
                if status in {403, 429} and self._wait_for_manual_unblock(page, f"HTTP {status}"):
                    status = self._load_detail_page_with_retries(page, record.restaurant_url)
                    if not status or status < 400:
                        logging.info(
                            "Manual unblock completed for detail page: %s", record.restaurant_url
                        )
                    else:
                        logging.warning(
                            "Detail page is still blocked after manual unblock: HTTP %s", status
                        )

                if not status or status < 400:
                    pass
                else:
                    logging.warning(
                        "Detail page returned HTTP %s: %s", status, record.restaurant_url
                    )
                    record.detail_scraped = False
                    record.scraped_at = scraped_at
                    self.last_http_status = status
                    self.last_failure_reason = f"http_{status}"
                    return record

            block_marker = self._detect_block_marker(page)
            if block_marker is not None:
                if self._wait_for_manual_unblock(page, f"block marker {block_marker!r}"):
                    block_marker = self._detect_block_marker(page)
                    if block_marker is None:
                        logging.info(
                            "Manual unblock cleared block marker for detail page: %s",
                            record.restaurant_url,
                        )

                if block_marker is not None:
                    logging.warning(
                        "Detail page contained block marker %r: %s",
                        block_marker,
                        record.restaurant_url,
                    )
                    record.detail_scraped = False
                    record.scraped_at = scraped_at
                    self.last_http_status = status
                    self.last_failure_reason = "blocked_page"
                    self.last_block_marker = block_marker
                    return record

            try:
                page.wait_for_load_state("networkidle", timeout=self.detail_timeout_ms)
            except PlaywrightTimeoutError:
                logging.debug("Detail page did not reach network idle: %s", record.restaurant_url)

            self._micro_reading_pause(page)
            self._light_human_scroll(page)
            self._micro_reading_pause(page)
            payload = self._extract_page_payload(page)
            detail_data = self._parse_detail_payload(payload, record)
            self._merge_detail_data(record, detail_data, scraped_at)
            record.detail_scraped = True
            return record
        except (PlaywrightError, PlaywrightTimeoutError) as error:
            logging.warning("Could not scrape detail page %s: %s", record.restaurant_url, error)
            record.detail_scraped = False
            record.scraped_at = scraped_at
            self.last_failure_reason = type(error).__name__
            return record

    def _wait_for_manual_unblock(self, page: Page, reason: str) -> bool:
        if not self.pause_on_block:
            return False

        print("\a")
        logging.warning(
            "TheFork anti-bot block detected (%s). Resolve it in the browser, "
            "then press Enter here.",
            reason,
        )
        input("TheFork block detected. Resolve the browser page, then press Enter to retry...")
        page.wait_for_timeout(int(random.uniform(1500, 2500)))
        return True

    def _micro_reading_pause(self, page: Page) -> None:
        if self.micro_pause_max_ms <= 0:
            return
        page.wait_for_timeout(int(random.uniform(self.micro_pause_min_ms, self.micro_pause_max_ms)))

    def _load_detail_page_with_retries(self, page: Page, url: str) -> int | None:
        status: int | None = None
        for attempt in range(self.max_block_retries + 1):
            response = page.goto(
                url, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms
            )
            status = response.status if response else None
            if status != 403:
                return status
            if attempt >= self.max_block_retries:
                return status
            logging.warning(
                "Detail page returned HTTP 403. Waiting briefly and retrying once: %s",
                url,
            )
            if self.block_retry_delay_ms > 0:
                page.wait_for_timeout(self.block_retry_delay_ms)
        return status

    def _detect_block_marker(self, page: Page) -> str | None:
        try:
            page_text = page.evaluate(
                """
                () => [
                  document.title || '',
                  (document.body && document.body.innerText) || '',
                  document.documentElement.outerHTML || '',
                ].join('\\n').slice(0, 50000)
                """
            )
        except PlaywrightError:
            return None

        normalized_text = (page_text or "").lower()
        for marker in BLOCK_MARKERS:
            if marker in normalized_text:
                return marker
        return None

    def _light_human_scroll(self, page: Page) -> None:
        if not self.human_scroll_enabled:
            return

        try:
            steps = random.randint(self.human_scroll_min_steps, self.human_scroll_max_steps)
            for _ in range(steps):
                page.mouse.wheel(0, random.randint(260, 560))
                page.wait_for_timeout(int(random.uniform(500, 1300)))

            if random.random() < 0.35:
                page.mouse.wheel(0, -random.randint(100, 240))
                page.wait_for_timeout(int(random.uniform(400, 900)))
        except PlaywrightError:
            logging.debug("Light human scroll failed, continuing extraction.")

    def _extract_page_payload(self, page: Page) -> dict[str, Any]:
        return page.evaluate(
            """
            (maxScriptChars) => {
              const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
              const getMeta = (selector) => {
                const element = document.querySelector(selector);
                return element ? element.getAttribute('content') : null;
              };
              const scripts = Array.from(document.querySelectorAll(
                'script[type="application/ld+json"], script[type="application/json"], ' +
                'script[id*="NEXT"], script[id*="state"], script[id*="apollo"]'
              )).map((script) => (script.textContent || '').slice(0, maxScriptChars));
              const links = Array.from(document.querySelectorAll('a[href]')).map((link) => ({
                href: link.href || link.getAttribute('href') || '',
                text: clean(link.innerText || link.textContent || ''),
                rel: link.getAttribute('rel') || '',
              }));
              const images = Array.from(
                document.querySelectorAll('img[src], source[srcset]')
              ).map((image) => ({
                src:
                  image.currentSrc ||
                  image.src ||
                  image.getAttribute('src') ||
                  image.getAttribute('srcset') ||
                  '',
                alt: image.getAttribute('alt') || '',
              }));
              const body = document.body || document.documentElement;
              return {
                page_url: location.href,
                canonical_url: document.querySelector('link[rel="canonical"]')?.href || null,
                title: document.title || null,
                og_title: getMeta('meta[property="og:title"]'),
                h1: clean(document.querySelector('h1')?.innerText || ''),
                body_text: (body.innerText || '').slice(0, 120000),
                json_scripts: scripts,
                links,
                images,
              };
            }
            """,
            MAX_SCRIPT_CHARS,
        )

    def _parse_detail_payload(
        self, payload: dict[str, Any], listing_record: RestaurantRecord
    ) -> dict[str, Any]:
        json_documents = parse_json_documents(payload.get("json_scripts") or [])
        structured = extract_structured_restaurant_data(json_documents)
        embedded = extract_embedded_data(
            json_documents, payload.get("body_text") or "", payload.get("links") or []
        )
        visible = extract_visible_data(payload)

        restaurant_url = normalize_restaurant_url(
            payload.get("canonical_url")
            or payload.get("page_url")
            or listing_record.restaurant_url
            or ""
        )

        return {
            "source_id": extract_source_id(restaurant_url or listing_record.restaurant_url or ""),
            "restaurant_name": first_value(
                structured.get("restaurant_name"),
                embedded.get("restaurant_name"),
                visible.get("restaurant_name"),
            ),
            "address": first_value(
                structured.get("address"), embedded.get("address"), visible.get("address")
            ),
            "latitude": first_value(
                structured.get("latitude"), embedded.get("latitude"), visible.get("latitude")
            ),
            "longitude": first_value(
                structured.get("longitude"), embedded.get("longitude"), visible.get("longitude")
            ),
            "rating": first_value(
                structured.get("rating"), embedded.get("rating"), visible.get("rating")
            ),
            "review_count": first_value(
                structured.get("review_count"),
                embedded.get("review_count"),
                visible.get("review_count"),
            ),
            "cuisine_type": first_value(
                structured.get("cuisine_type"),
                embedded.get("cuisine_type"),
                visible.get("cuisine_type"),
            ),
            "price_range": first_value(
                structured.get("price_range"),
                embedded.get("price_range"),
                visible.get("price_range"),
            ),
            "discount": first_value(embedded.get("discount"), visible.get("discount")),
            "photo_count": first_value(
                structured.get("photo_count"),
                embedded.get("photo_count"),
                visible.get("photo_count"),
            ),
            "website": first_value(
                structured.get("website"), embedded.get("website"), visible.get("website")
            ),
            "phone_number": first_value(
                structured.get("phone_number"),
                embedded.get("phone_number"),
                visible.get("phone_number"),
            ),
            "email": first_value(
                structured.get("email"), embedded.get("email"), visible.get("email")
            ),
            "working_days_hours": first_value(
                structured.get("working_days_hours"), embedded.get("working_days_hours")
            ),
            "restaurant_url": restaurant_url,
            "review_snippets": unique_texts(
                [*(embedded.get("review_snippets") or []), *(visible.get("review_snippets") or [])]
            ),
            "reviews": merge_reviews(
                structured.get("reviews") or [],
                embedded.get("reviews") or [],
                max_reviews=self.max_reviews_per_restaurant,
            ),
        }

    def _merge_detail_data(
        self,
        record: RestaurantRecord,
        detail_data: dict[str, Any],
        scraped_at: str,
    ) -> None:
        for field_name in (
            "source_id",
            "restaurant_name",
            "address",
            "latitude",
            "longitude",
            "rating",
            "review_count",
            "cuisine_type",
            "price_range",
            "discount",
            "photo_count",
            "website",
            "phone_number",
            "email",
            "working_days_hours",
            "restaurant_url",
        ):
            value = detail_data.get(field_name)
            if value not in (None, "", []):
                setattr(record, field_name, value)

        record.review_snippets = unique_texts(
            [*record.review_snippets, *(detail_data.get("review_snippets") or [])]
        )
        if detail_data.get("reviews"):
            record.reviews = detail_data["reviews"]
        record.scraped_at = scraped_at


def parse_json_documents(raw_scripts: Iterable[str]) -> list[Any]:
    documents: list[Any] = []
    for raw_script in raw_scripts:
        raw_script = (raw_script or "").strip()
        if not raw_script:
            continue
        try:
            documents.append(json.loads(raw_script))
        except json.JSONDecodeError:
            continue
    return documents


def extract_structured_restaurant_data(json_documents: list[Any]) -> dict[str, Any]:
    nodes = list(iter_json_nodes(json_documents))
    restaurant_node = first_restaurant_node(nodes)
    if restaurant_node is None:
        return {}

    aggregate_rating = object_value(restaurant_node.get("aggregateRating"))
    geo = object_value(restaurant_node.get("geo"))
    image_value = restaurant_node.get("image")

    return {
        "restaurant_name": clean_optional(restaurant_node.get("name")),
        "address": normalize_address(restaurant_node.get("address")),
        "latitude": parse_float(
            first_value(geo.get("latitude") if geo else None, geo.get("lat") if geo else None)
        ),
        "longitude": parse_float(
            first_value(geo.get("longitude") if geo else None, geo.get("lng") if geo else None)
        ),
        "rating": parse_float(aggregate_rating.get("ratingValue") if aggregate_rating else None),
        "review_count": parse_int(
            aggregate_rating.get("reviewCount") if aggregate_rating else None
        ),
        "cuisine_type": normalize_list_value(
            first_value(restaurant_node.get("servesCuisine"), restaurant_node.get("cuisine"))
        ),
        "price_range": normalize_price(
            first_value(restaurant_node.get("priceRange"), restaurant_node.get("price"))
        ),
        "website": normalize_external_url(
            first_value(restaurant_node.get("url"), first_list_value(restaurant_node.get("sameAs")))
        ),
        "phone_number": clean_optional(restaurant_node.get("telephone")),
        "email": clean_optional(restaurant_node.get("email")),
        "working_days_hours": normalize_hours(
            first_value(
                restaurant_node.get("openingHoursSpecification"),
                restaurant_node.get("openingHours"),
            )
        ),
        "photo_count": count_images(image_value),
        "reviews": extract_reviews(restaurant_node.get("review")),
    }


def extract_embedded_data(
    json_documents: list[Any], body_text: str, links: list[dict[str, str]]
) -> dict[str, Any]:
    nodes = list(iter_json_nodes(json_documents))
    scripts_text = "\n".join(
        json.dumps(document, ensure_ascii=False)[:MAX_SCRIPT_CHARS] for document in json_documents
    )
    latitude, longitude = extract_coordinates_from_text(scripts_text + "\n" + body_text)

    return {
        "restaurant_name": clean_optional(first_json_value(nodes, {"restaurantName", "name"})),
        "address": normalize_address(first_json_value(nodes, {"address", "streetAddress"})),
        "latitude": latitude or parse_float(first_json_value(nodes, {"latitude", "lat"})),
        "longitude": longitude or parse_float(first_json_value(nodes, {"longitude", "lng"})),
        "rating": parse_float(first_json_value(nodes, {"ratingValue", "rating"})),
        "review_count": parse_int(
            first_json_value(nodes, {"reviewCount", "reviewsCount", "numberOfReviews"})
        ),
        "cuisine_type": normalize_list_value(
            first_json_value(nodes, {"servesCuisine", "cuisine", "category", "categories"})
        ),
        "price_range": normalize_price(
            first_json_value(nodes, {"priceRange", "averagePrice", "price"})
        ),
        "discount": extract_discount_from_text(scripts_text + "\n" + body_text),
        "photo_count": first_value(
            count_images(first_json_value(nodes, {"image", "images", "photos", "photo"})),
            count_visible_images_from_links(links),
        ),
        "website": normalize_external_url(
            first_json_value(nodes, {"website", "officialWebsite", "url"})
        ),
        "phone_number": clean_optional(
            first_json_value(nodes, {"telephone", "phone", "phoneNumber"})
        ),
        "email": clean_optional(first_json_value(nodes, {"email"})),
        "working_days_hours": normalize_hours(
            first_json_value(nodes, {"openingHoursSpecification", "openingHours", "hours"})
        ),
        "review_snippets": extract_review_snippets_from_text(body_text),
        "reviews": extract_reviews_from_nodes(nodes),
    }


def extract_visible_data(payload: dict[str, Any]) -> dict[str, Any]:
    body_text = payload.get("body_text") or ""
    lines = split_visible_lines(body_text)
    links = payload.get("links") or []
    images = payload.get("images") or []
    latitude, longitude = extract_coordinates_from_links(links)
    if latitude is None or longitude is None:
        latitude, longitude = extract_coordinates_from_text(body_text)

    return {
        "restaurant_name": clean_optional(first_value(payload.get("h1"), payload.get("og_title"))),
        "address": extract_address_from_lines(lines),
        "latitude": latitude,
        "longitude": longitude,
        "rating": extract_visible_rating(lines),
        "review_count": extract_visible_review_count(lines),
        "cuisine_type": extract_visible_cuisine(lines),
        "price_range": extract_visible_price(lines),
        "discount": extract_discount_from_text(body_text),
        "photo_count": extract_visible_photo_count(body_text, images),
        "website": extract_website_from_links(links),
        "phone_number": extract_phone_from_links_or_text(links, body_text),
        "email": extract_email_from_links_or_text(links, body_text),
        "review_snippets": extract_review_snippets_from_text(body_text),
    }


def iter_json_nodes(value: Any) -> Iterable[dict[str, Any]]:
    stack = [value]
    visited = 0
    while stack and visited < 50_000:
        visited += 1
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def first_restaurant_node(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for node in nodes:
        type_value = node.get("@type")
        if isinstance(type_value, list):
            type_text = " ".join(str(item) for item in type_value)
        else:
            type_text = str(type_value or "")
        if re.search(r"Restaurant|FoodEstablishment|LocalBusiness", type_text, re.IGNORECASE):
            return node
    return None


def first_json_value(nodes: list[dict[str, Any]], keys: set[str]) -> Any:
    lowered_keys = {key.lower() for key in keys}
    for node in nodes:
        for key, value in node.items():
            if key.lower() in lowered_keys and value not in (None, "", [], {}):
                return value
    return None


def object_value(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def normalize_address(value: Any) -> str | None:
    if isinstance(value, str):
        return clean_optional(value)
    if isinstance(value, dict):
        country = value.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        parts = [
            value.get("streetAddress"),
            value.get("addressLocality"),
            value.get("postalCode"),
            value.get("addressRegion"),
            country,
        ]
        return clean_optional(", ".join(str(part) for part in parts if part))
    return None


def normalize_list_value(value: Any) -> str | None:
    if isinstance(value, list):
        return clean_optional(", ".join(str(item) for item in value if item))
    if isinstance(value, dict):
        return clean_optional(first_value(value.get("name"), value.get("label")))
    return clean_optional(value)


def normalize_price(value: Any) -> str | None:
    if value is None:
        return None
    text = clean_spaces(str(value))
    if not text:
        return None
    match = PRICE_TEXT_PATTERN.search(text)
    if match:
        amount = clean_spaces(match.group(1)).replace("EUR", "\u20ac")
        if "\u20ac" not in amount:
            amount = f"{amount} \u20ac"
        return amount
    amount_match = re.search(r"([\d.,]+)\s*(?:\u20ac|EUR)", text, re.IGNORECASE)
    if amount_match:
        return f"{amount_match.group(1)} \u20ac"
    if "\u20ac" in text:
        return text
    return text


def normalize_external_url(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            normalized = normalize_external_url(item)
            if normalized:
                return normalized
        return None
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url.startswith(("http://", "https://")):
        return None
    host = urlparse(url).netloc.lower()
    if THEFORK_HOST in host or "thefork." in host:
        return None
    excluded_hosts = ("google.", "facebook.", "instagram.", "tripadvisor.", "youtube.", "tiktok.")
    if any(host_part in host for host_part in excluded_hosts):
        return None
    return url


def normalize_hours(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, str):
        return clean_optional(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d+(?:[,.]\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    return int(digits) if digits else None


def first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def first_list_value(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return value


def clean_optional(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = clean_spaces(str(value))
    if not text:
        return None
    if text.lower() in {"menu", "reviews", "recensioni", "photos", "foto", "prenota", "book"}:
        return None
    return text


def count_images(value: Any) -> int | None:
    if isinstance(value, list):
        urls = {str(item) for item in value if str(item).startswith(("http://", "https://"))}
        return len(urls) or None
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return 1
    return None


def count_visible_images_from_links(links: list[dict[str, str]]) -> int | None:
    urls = {
        link.get("href", "")
        for link in links
        if isinstance(link.get("href"), str)
        and re.search(r"\.(?:jpg|jpeg|png|webp)(?:[?#]|$)", link.get("href", ""), re.IGNORECASE)
    }
    return len(urls) or None


def extract_coordinates_from_links(
    links: list[dict[str, str]],
) -> tuple[float | None, float | None]:
    return extract_coordinates_from_text("\n".join(link.get("href", "") for link in links))


def extract_coordinates_from_text(text: str) -> tuple[float | None, float | None]:
    for pattern in COORDINATE_PAIR_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return parse_float(match.group(1)), parse_float(match.group(2))

    lat_match = re.search(r'"(?:latitude|lat)"\s*:\s*(-?\d{1,2}\.\d+)', text or "", re.IGNORECASE)
    lng_match = re.search(
        r'"(?:longitude|lng|lon)"\s*:\s*(-?\d{1,3}\.\d+)', text or "", re.IGNORECASE
    )
    if lat_match and lng_match:
        return parse_float(lat_match.group(1)), parse_float(lng_match.group(1))
    return None, None


def extract_address_from_lines(lines: list[str]) -> str | None:
    street_pattern = re.compile(
        r"\b(?:via|viale|piazza|corso|largo|vicolo|alzaia|foro|ripa|strada|bastioni)\b",
        re.IGNORECASE,
    )
    for line in lines:
        if "Milano" in line and street_pattern.search(line):
            return line
    for line in lines:
        if street_pattern.search(line) and len(line) <= 140:
            return line
    return None


def extract_visible_rating(lines: list[str]) -> float | None:
    for line in lines:
        if re.fullmatch(r"(?:[0-9]|10)[,.][0-9]", line):
            return parse_float(line)
    return None


def extract_visible_review_count(lines: list[str]) -> int | None:
    for line in lines:
        match = REVIEW_COUNT_TEXT_PATTERN.search(line)
        if match:
            return parse_int(match.group(1))
    return extract_review_count(lines)


def extract_visible_cuisine(lines: list[str]) -> str | None:
    bad_tokens = ("prezzo", "sconto", "recension", "menu", "foto", "prenota")
    for line in lines:
        lowered = line.lower()
        if any(token in lowered for token in bad_tokens):
            continue
        if len(line) <= 80 and re.search(
            r"\b(?:italian[ao]?|mediterrane[ao]?|pizza|pesce|sushi|japanese|asian|europe[ao]?|lombard[ao]?)\b",
            lowered,
        ):
            return line
    return None


def extract_visible_price(lines: list[str]) -> str | None:
    price = extract_price_range(lines)
    if price:
        return price
    for line in lines:
        price = normalize_price(line)
        if price and re.search(r"(?:prezzo|average price|\u20ac)", line, re.IGNORECASE):
            return price
    return None


def extract_discount_from_text(text: str) -> str | None:
    match = DISCOUNT_TEXT_PATTERN.search(text or "")
    return clean_optional(match.group(0)) if match else None


def extract_visible_photo_count(body_text: str, images: list[dict[str, str]]) -> int | None:
    slide_match = SLIDE_COUNT_PATTERN.search(body_text or "")
    if slide_match:
        return parse_int(slide_match.group(1))

    image_urls = {
        image.get("src", "").split(" ")[0]
        for image in images
        if is_restaurant_image_url(image.get("src", ""), image.get("alt", ""))
    }
    return len(image_urls) or None


def is_restaurant_image_url(url: str, alt: str) -> bool:
    value = f"{url} {alt}".lower()
    if not url.startswith(("http://", "https://")):
        return False
    excluded = ("logo", "icon", "avatar", "pixel", "sprite", "badge", "tracking")
    return not any(token in value for token in excluded)


def extract_website_from_links(links: list[dict[str, str]]) -> str | None:
    preferred: list[str] = []
    fallback: list[str] = []
    for link in links:
        href = link.get("href", "")
        text = link.get("text", "")
        normalized = normalize_external_url(href)
        if not normalized:
            continue
        if re.search(r"\b(?:sito|website|web)\b", text, re.IGNORECASE):
            preferred.append(normalized)
        else:
            fallback.append(normalized)
    return first_value(*(preferred + fallback))


def extract_phone_from_links_or_text(links: list[dict[str, str]], body_text: str) -> str | None:
    for link in links:
        href = link.get("href", "")
        if href.startswith("tel:"):
            return clean_optional(href.removeprefix("tel:"))
    match = PHONE_PATTERN.search(body_text or "")
    return clean_optional(match.group(0)) if match else None


def extract_email_from_links_or_text(links: list[dict[str, str]], body_text: str) -> str | None:
    for link in links:
        href = link.get("href", "")
        if href.startswith("mailto:"):
            return clean_optional(href.removeprefix("mailto:").split("?", maxsplit=1)[0])
    match = EMAIL_PATTERN.search(body_text or "")
    return clean_optional(match.group(0)) if match else None


def extract_review_snippets_from_text(body_text: str) -> list[str]:
    snippets: list[str] = []
    for line in split_visible_lines(body_text):
        if re.search(r"\b(?:sconto|discount|off|prezzo|average price)\b", line, re.IGNORECASE):
            continue
        if 40 <= len(line) <= 260 and re.search(
            r"\b(?:ottim|excellent|servizio|cibo|food|locale|restaurant)\b", line, re.IGNORECASE
        ):
            snippets.append(line)
        if len(snippets) >= 5:
            break
    return unique_texts(snippets)


def extract_reviews(value: Any) -> list[dict[str, Any]]:
    if value in (None, "", [], {}):
        return []
    review_values = value if isinstance(value, list) else [value]
    reviews: list[dict[str, Any]] = []
    for item in review_values:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        rating = item.get("reviewRating") or item.get("rating")
        review = {
            "author_name": clean_optional(
                author.get("name") if isinstance(author, dict) else author
            ),
            "rating": parse_float(
                rating.get("ratingValue") if isinstance(rating, dict) else rating
            ),
            "title": clean_optional(item.get("name") or item.get("headline")),
            "text": clean_optional(
                item.get("reviewBody") or item.get("text") or item.get("description")
            ),
            "date": clean_optional(item.get("datePublished") or item.get("date")),
        }
        if review["text"] or review["title"]:
            reviews.append(review)
    return reviews


def extract_reviews_from_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for node in nodes:
        keys = {key.lower() for key in node.keys()}
        if {"reviewbody"} & keys or ("text" in keys and ("rating" in keys or "author" in keys)):
            reviews.extend(extract_reviews(node))
    return reviews


def merge_reviews(*review_lists: list[dict[str, Any]], max_reviews: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for review_list in review_lists:
        for review in review_list:
            key = clean_spaces(
                f"{review.get('author_name') or ''}|{review.get('date') or ''}|"
                f"{review.get('text') or ''}"
            ).casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(review)
            if len(merged) >= max_reviews:
                return merged
    return merged


def unique_texts(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = clean_optional(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
