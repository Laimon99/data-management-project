from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

from .models import RestaurantRecord
from .parser import clean_spaces, extract_source_id, normalize_restaurant_url
from .storage import JsonStorage


RESTAURANT_ID_PATTERN = re.compile(r"-r(\d+)(?:\D|$)")

GRAPHQL_DETAIL_QUERY = """
query RestaurantJsonLD($restaurantId: ID!, $reviewSize: PositiveInt!) {
  restaurant(restaurantId: $restaurantId) {
    id
    hasNoGoogleLinkTag
    isAffiliated
    name
    url
    legacyId
    slug
    servesCuisine
    paymentAccepted
    reviewsSummary { content }
    photos(withRawUrl: true) { id src: imageUrl alt }
    customerPhotos(pagination: { limit: 30 }) { photos { id src: imageUrl } }
    address { street zipCode locality country }
    geolocation { longitude latitude }
    avgPrice { value currency { isoCurrency decimalPosition } }
    insiderDescription
    description
    aggregateRatings { thefork { ratingValue reviewCount } }
    tags { id name category { id } isPublished }
    isTest
    hasStock
    isBookable
    marketingOffer { offer { ... on Promotion { id name discountPercentage } } }
    menu { aLaCarte { id updatedTs } presetMenus { id updatedTs } }
    openingTimeInformation {
      openingHours {
        mon { start end }
        tue { start end }
        wed { start end }
        thu { start end }
        fri { start end }
        sat { start end }
        sun { start end }
      }
    }
  }
  restaurantRatingsList(
    restaurantId: $restaurantId
    pagination: { limit: $reviewSize }
    orderBy: MEAL_DATE
    sortDirection: DESC
  ) {
    ratings {
      id
      mealDate
      ratingValue
      review { reviewBody }
      photos { id imageUrl }
      reviewer { id reviewCount lastName firstName avatar: avatarUrl }
    }
  }
}
"""


@dataclass(frozen=True, slots=True)
class GraphQLDetailOptions:
    connect_over_cdp_url: str
    max_records: int | None = None
    review_size: int = 5
    delay_min_seconds: float = 60.0
    delay_max_seconds: float = 180.0
    partial_every_records: int = 25
    max_consecutive_failures: int = 3
    detail_shard_count: int = 1
    detail_shard_index: int = 1
    report_path: Path | None = None


def run_graphql_detail_enrichment(storage: JsonStorage, options: GraphQLDetailOptions) -> dict[str, Any]:
    records = storage.load_partial()
    if not records:
        raise RuntimeError("No partial records found. Run listing scraping or pass --input-partial first.")

    all_pending_indexes = [
        index
        for index, record in enumerate(records, start=1)
        if not record.detail_scraped and record.restaurant_url
    ]
    pending_indexes = [
        record_index
        for pending_position, record_index in enumerate(all_pending_indexes, start=1)
        if pending_position_belongs_to_shard(pending_position, options)
    ]
    if options.max_records is not None:
        pending_indexes = pending_indexes[: max(0, options.max_records)]

    report: dict[str, Any] = {
        "source": "thefork",
        "mode": "graphql_detail_from_cdp",
        "created_at": utc_timestamp(),
        "connect_over_cdp_url": options.connect_over_cdp_url,
        "initial_total_records": len(records),
        "initial_pending_in_scope": len(pending_indexes),
        "attempted": 0,
        "succeeded": 0,
        "failed": 0,
        "failed_urls": [],
        "succeeded_urls": [],
        "stopped_reason": None,
    }

    if not pending_indexes:
        logging.info("No pending detail records matched the configured scope.")
        save_graphql_report(storage, options, report)
        return report

    logging.info("Starting TheFork GraphQL/CDP detail enrichment for %s pending records.", len(pending_indexes))

    consecutive_failures = 0
    processed_since_save = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(options.connect_over_cdp_url)
        try:
            page = find_thefork_page(browser.contexts)
            if page is None:
                raise RuntimeError("No open TheFork tab found in the connected browser.")

            for record_index in pending_indexes:
                record = records[record_index - 1]
                restaurant_id = extract_restaurant_legacy_id(record.restaurant_url)
                if not restaurant_id:
                    report["failed"] += 1
                    report["failed_urls"].append(record.restaurant_url)
                    continue

                report["attempted"] += 1
                logging.info(
                    "GraphQL detail enrichment %s/%s: record %s %s",
                    report["attempted"],
                    len(pending_indexes),
                    record_index,
                    record.restaurant_url,
                )

                try:
                    payload = fetch_graphql_detail(page, restaurant_id, options.review_size)
                    merge_graphql_detail(record, payload, utc_timestamp())
                except Exception as error:
                    consecutive_failures += 1
                    report["failed"] += 1
                    report["failed_urls"].append(record.restaurant_url)
                    logging.warning("GraphQL detail enrichment failed for %s: %s", record.restaurant_url, error)
                    if consecutive_failures >= options.max_consecutive_failures:
                        report["stopped_reason"] = f"{consecutive_failures}_consecutive_failures"
                        logging.warning("Stopping GraphQL enrichment after %s consecutive failures.", consecutive_failures)
                        break
                else:
                    consecutive_failures = 0
                    processed_since_save += 1
                    report["succeeded"] += 1
                    report["succeeded_urls"].append(record.restaurant_url)
                    logging.info("GraphQL detail enrichment completed: %s", record.restaurant_url)

                if processed_since_save >= max(1, options.partial_every_records):
                    storage.save_partial(records)
                    processed_since_save = 0

                wait_between_records(options)
        finally:
            browser.close()

    storage.save_partial(records)
    save_graphql_report(storage, options, report)
    logging.info(
        "GraphQL/CDP detail enrichment finished. Attempted=%s succeeded=%s failed=%s",
        report["attempted"],
        report["succeeded"],
        report["failed"],
    )
    return report


def pending_position_belongs_to_shard(pending_position: int, options: GraphQLDetailOptions) -> bool:
    return ((pending_position - 1) % options.detail_shard_count) + 1 == options.detail_shard_index


def find_thefork_page(contexts: Any) -> Page | None:
    pages = [page for context in contexts for page in context.pages]
    for page in pages:
        if "thefork." in page.url:
            return page
    return None


def fetch_graphql_detail(page: Page, restaurant_id: str, review_size: int) -> dict[str, Any]:
    response = page.evaluate(
        """
        async ({ query, restaurantId, reviewSize }) => {
          const response = await fetch('/api/graphql', {
            method: 'POST',
            credentials: 'include',
            headers: {
              'accept': '*/*',
              'content-type': 'application/json',
              'apollographql-client-name': 'thefork-web',
            },
            body: JSON.stringify({
              operationName: 'RestaurantJsonLD',
              variables: { restaurantId, reviewSize },
              query,
            }),
          });
          const text = await response.text();
          let parsed = null;
          try {
            parsed = JSON.parse(text);
          } catch (error) {
            parsed = null;
          }
          return {
            status: response.status,
            contentType: response.headers.get('content-type'),
            textStart: text.slice(0, 500),
            parsed,
          };
        }
        """,
        {
            "query": GRAPHQL_DETAIL_QUERY,
            "restaurantId": restaurant_id,
            "reviewSize": max(0, review_size),
        },
    )
    status = response.get("status")
    if status != 200:
        raise RuntimeError(f"GraphQL HTTP {status}: {response.get('textStart')}")

    payload = response.get("parsed")
    if not isinstance(payload, dict):
        raise RuntimeError(f"GraphQL returned non-JSON response: {response.get('textStart')}")
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL validation/runtime errors: {payload['errors']}")
    data = payload.get("data")
    if not isinstance(data, dict) or not data.get("restaurant"):
        raise RuntimeError("GraphQL response did not include restaurant data.")
    return data


def merge_graphql_detail(record: RestaurantRecord, payload: dict[str, Any], scraped_at: str) -> None:
    restaurant = payload.get("restaurant") or {}
    ratings = ((payload.get("restaurantRatingsList") or {}).get("ratings") or [])
    restaurant_url = normalize_restaurant_url(restaurant.get("url") or record.restaurant_url or "")
    address = parse_address(restaurant.get("address") or {})
    rating_values = (restaurant.get("aggregateRatings") or {}).get("thefork") or {}
    avg_price = parse_money(restaurant.get("avgPrice"))
    photo_count = count_photos(restaurant)

    field_values = {
        "source_id": extract_source_id(restaurant_url or record.restaurant_url or ""),
        "restaurant_name": clean_optional(restaurant.get("name")),
        "address": address,
        "latitude": parse_float((restaurant.get("geolocation") or {}).get("latitude")),
        "longitude": parse_float((restaurant.get("geolocation") or {}).get("longitude")),
        "rating": parse_float(rating_values.get("ratingValue")),
        "review_count": parse_int(rating_values.get("reviewCount")),
        "cuisine_type": clean_optional(restaurant.get("servesCuisine")),
        "price_range": avg_price,
        "discount": parse_discount(restaurant),
        "photo_count": photo_count,
        "working_days_hours": parse_opening_hours(restaurant),
        "working_hours_structured": parse_opening_hours_structured(restaurant),
        "restaurant_url": restaurant_url,
    }

    for field_name, value in field_values.items():
        if value not in (None, "", []):
            setattr(record, field_name, value)

    reviews = parse_reviews(ratings)
    if reviews:
        record.reviews = reviews
        record.review_snippets = unique_texts(
            [*record.review_snippets, *(review["text"] for review in reviews if review.get("text"))]
        )
    elif (restaurant.get("reviewsSummary") or {}).get("content"):
        record.review_snippets = unique_texts([*record.review_snippets, restaurant["reviewsSummary"]["content"]])

    record.detail_scraped = True
    record.scraped_at = scraped_at


def extract_restaurant_legacy_id(url: str | None) -> str | None:
    if not url:
        return None
    match = RESTAURANT_ID_PATTERN.search(url)
    return match.group(1) if match else None


def parse_address(address: dict[str, Any]) -> str | None:
    parts = [
        clean_optional(address.get("street")),
        clean_optional(address.get("locality")),
        clean_optional(address.get("zipCode")),
        clean_optional(address.get("country")),
    ]
    cleaned_parts = [part for part in parts if part]
    return ", ".join(cleaned_parts) if cleaned_parts else None


def parse_money(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    raw_amount = parse_float(value.get("value"))
    if raw_amount is None:
        return None
    currency = value.get("currency") or {}
    decimal_position = parse_int(currency.get("decimalPosition"))
    amount = raw_amount / (10 ** decimal_position) if decimal_position is not None else raw_amount
    amount_text = str(int(amount)) if amount.is_integer() else f"{amount:.2f}".rstrip("0").rstrip(".")
    iso_currency = clean_optional(currency.get("isoCurrency")) or ""
    symbol = "\u20ac" if iso_currency == "EUR" else iso_currency
    return clean_spaces(f"{amount_text} {symbol}") if symbol else amount_text


def parse_discount(restaurant: dict[str, Any]) -> str | None:
    offer = ((restaurant.get("marketingOffer") or {}).get("offer") or {})
    percentage = parse_int(offer.get("discountPercentage"))
    if percentage:
        return f"sconto -{percentage}%"
    return clean_optional(offer.get("name"))


def count_photos(restaurant: dict[str, Any]) -> int | None:
    restaurant_photos = restaurant.get("photos") or []
    customer_photos = ((restaurant.get("customerPhotos") or {}).get("photos") or [])
    photo_ids = {
        clean_optional(photo.get("id")) or clean_optional(photo.get("src")) or clean_optional(photo.get("imageUrl"))
        for photo in [*restaurant_photos, *customer_photos]
        if isinstance(photo, dict)
    }
    photo_ids.discard(None)
    return len(photo_ids) if photo_ids else None


def parse_opening_hours(restaurant: dict[str, Any]) -> str | None:
    specifications = parse_opening_hours_structured(restaurant)
    return json.dumps(specifications, ensure_ascii=False) if specifications else None


def parse_opening_hours_structured(restaurant: dict[str, Any]) -> list[dict[str, Any]]:
    opening_hours = (
        ((restaurant.get("openingTimeInformation") or {}).get("openingHours") or {})
        if isinstance(restaurant, dict)
        else {}
    )
    if not opening_hours:
        return []

    day_names = {
        "mon": "luned\u00ec",
        "tue": "marted\u00ec",
        "wed": "mercoled\u00ec",
        "thu": "gioved\u00ec",
        "fri": "venerd\u00ec",
        "sat": "sabato",
        "sun": "domenica",
    }
    specifications: list[dict[str, Any]] = []
    for day_key, day_name in day_names.items():
        intervals = opening_hours.get(day_key) or []
        for interval in intervals:
            start = minutes_to_time(interval.get("start"))
            end = minutes_to_time(interval.get("end"))
            if start and end:
                specifications.append(
                    {
                        "@type": "OpeningHoursSpecification",
                        "closes": end,
                        "dayOfWeek": [day_name],
                        "opens": start,
                    }
                )
    return specifications


def minutes_to_time(value: Any) -> str | None:
    minutes = parse_int(value)
    if minutes is None:
        return None
    hours, remainder = divmod(minutes, 60)
    return f"{hours:02d}:{remainder:02d}"


def parse_reviews(ratings: list[Any]) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for rating in ratings:
        if not isinstance(rating, dict):
            continue
        review = rating.get("review") or {}
        text = clean_optional(review.get("reviewBody"))
        if not text:
            continue
        reviewer = rating.get("reviewer") or {}
        author = clean_spaces(
            " ".join(
                part
                for part in [
                    clean_optional(reviewer.get("firstName")),
                    clean_optional(reviewer.get("lastName")),
                ]
                if part
            )
        )
        reviews.append(
            {
                "author_name": author or None,
                "rating": parse_float(rating.get("ratingValue")),
                "title": None,
                "text": text,
                "date": parse_date(rating.get("mealDate")),
            }
        )
    return reviews


def parse_date(value: Any) -> str | None:
    text = clean_optional(value)
    if not text:
        return None
    return text.split("T", 1)[0]


def wait_between_records(options: GraphQLDetailOptions) -> None:
    min_delay = max(0.0, options.delay_min_seconds)
    max_delay = max(min_delay, options.delay_max_seconds)
    delay = random.uniform(min_delay, max_delay)
    if delay > 0:
        logging.info("Waiting %.1f seconds before next GraphQL detail request.", delay)
        time.sleep(delay)


def save_graphql_report(storage: JsonStorage, options: GraphQLDetailOptions, report: dict[str, Any]) -> None:
    report_path = options.report_path or storage.output_dir / "thefork_graphql_detail_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_suffix(report_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as output_file:
        json.dump(report, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    temporary_path.replace(report_path)
    logging.info("Saved GraphQL detail report to %s", report_path)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = clean_optional(value)
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def parse_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = clean_optional(value)
    if not text:
        return None
    normalized = text.replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = clean_spaces(str(value))
    return text or None


def unique_texts(values: list[str]) -> list[str]:
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
