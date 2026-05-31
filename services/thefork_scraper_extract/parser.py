from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from .models import RestaurantRecord

THEFORK_BASE_URL = "https://www.thefork.it"
RESTAURANT_PATH_PATTERN = re.compile(r"/ristorante/[^/?#]+-r\d+", re.IGNORECASE)
SOURCE_ID_PATTERN = re.compile(r"/ristorante/([^/?#]+)", re.IGNORECASE)
RATING_PATTERN = re.compile(r"^(?:[0-9]|10)[,.][0-9]$")
REVIEW_COUNT_PATTERN = re.compile(r"^\(([\d\s.,]+)\)$")
PRICE_PATTERN = re.compile(r"^Prezzo\s+medio\s+(.+)$", re.IGNORECASE)
DISCOUNT_PATTERN = re.compile(r"\bScont[io]\b.*\d+\s*%", re.IGNORECASE)
SLIDE_PATTERN = re.compile(r"^Slide\s+\d+\s+di\s+\d+$", re.IGNORECASE)
SLIDE_COUNT_PATTERN = re.compile(r"^Slide\s+\d+\s+di\s+(\d+)$", re.IGNORECASE)
TIME_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")
PERCENT_PATTERN = re.compile(r"^-\d+\s*%$")
ONLY_NUMBER_PATTERN = re.compile(r"^\d+$")

BADGE_LINES = {
    "insider",
    "top100",
    "top host",
    "yums doppi",
    "michelin",
}

NON_CUISINE_LINES = {
    "hai in mente un altro orario?",
    "trova disponibilita",
    "trova disponibilità",
    "calcio e sport live",
}


def parse_restaurant_card(
    restaurant_url: str,
    card_text: str,
    aria_label: str | None,
    scraped_at: str,
    source_page_number: int,
) -> RestaurantRecord | None:
    normalized_url = normalize_restaurant_url(restaurant_url)
    if normalized_url is None:
        return None

    lines = split_visible_lines(card_text)
    address_index = find_address_index(lines)
    price_index = find_price_index(lines)

    restaurant_name = normalize_optional_text(aria_label)
    if not restaurant_name:
        restaurant_name = extract_name_from_lines(lines, address_index)

    address = lines[address_index] if address_index is not None else None

    return RestaurantRecord(
        source_id=extract_source_id(normalized_url),
        restaurant_name=restaurant_name,
        address=address,
        rating=extract_rating(lines),
        review_count=extract_review_count(lines),
        cuisine_type=extract_cuisine_type(lines, address_index, price_index),
        price_range=extract_price_range(lines),
        discount=extract_discount(lines),
        photo_count=extract_photo_count(lines),
        restaurant_url=normalized_url,
        review_snippets=extract_review_snippets(lines),
        scraped_at=scraped_at,
        source_page_number=source_page_number,
    )


def normalize_restaurant_url(raw_url: str) -> str | None:
    absolute_url = urljoin(THEFORK_BASE_URL, raw_url)
    parsed_url = urlsplit(absolute_url)
    if not RESTAURANT_PATH_PATTERN.search(parsed_url.path):
        return None
    return urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", ""))


def extract_source_id(restaurant_url: str) -> str | None:
    match = SOURCE_ID_PATTERN.search(urlsplit(restaurant_url).path)
    return match.group(1) if match else None


def split_visible_lines(text: str) -> list[str]:
    normalized_text = text.replace("\r", "\n").replace("\u00a0", " ").replace("\u202f", " ")
    lines = []
    for line in normalized_text.split("\n"):
        cleaned_line = clean_spaces(line)
        if cleaned_line:
            lines.append(cleaned_line)
    return lines


def normalize_optional_text(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned_text = clean_spaces(text)
    if not cleaned_text or SLIDE_PATTERN.match(cleaned_text):
        return None
    return cleaned_text


def clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def find_address_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if re.search(r"\bMilano\b", line, re.IGNORECASE):
            return index
    return None


def find_price_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if PRICE_PATTERN.match(line):
            return index
    return None


def extract_name_from_lines(lines: list[str], address_index: int | None) -> str | None:
    if address_index is not None:
        for index in range(address_index - 1, -1, -1):
            candidate = lines[index]
            if is_name_candidate(candidate):
                return candidate

    for candidate in lines:
        if is_name_candidate(candidate):
            return candidate
    return None


def is_name_candidate(line: str) -> bool:
    lowered_line = line.lower()
    return not (
        SLIDE_PATTERN.match(line)
        or ONLY_NUMBER_PATTERN.match(line)
        or RATING_PATTERN.match(line)
        or REVIEW_COUNT_PATTERN.match(line)
        or lowered_line in BADGE_LINES
        or PRICE_PATTERN.match(line)
        or DISCOUNT_PATTERN.search(line)
        or TIME_PATTERN.match(line)
        or PERCENT_PATTERN.match(line)
        or line.startswith("\u201c")
    )


def extract_rating(lines: list[str]) -> float | None:
    for line in lines:
        if RATING_PATTERN.match(line):
            return float(line.replace(",", "."))
    return None


def extract_review_count(lines: list[str]) -> int | None:
    for line in lines:
        match = REVIEW_COUNT_PATTERN.match(line)
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            if digits:
                return int(digits)
    return None


def extract_cuisine_type(
    lines: list[str],
    address_index: int | None,
    price_index: int | None,
) -> str | None:
    if address_index is None:
        return None

    end_index = price_index if price_index is not None else len(lines)
    for index in range(end_index - 1, address_index, -1):
        candidate = lines[index]
        if is_cuisine_candidate(candidate):
            return candidate

    for index in range(address_index + 1, len(lines)):
        candidate = lines[index]
        if is_cuisine_candidate(candidate):
            return candidate
    return None


def is_cuisine_candidate(line: str) -> bool:
    lowered_line = line.lower()
    return not (
        RATING_PATTERN.match(line)
        or REVIEW_COUNT_PATTERN.match(line)
        or PRICE_PATTERN.match(line)
        or DISCOUNT_PATTERN.search(line)
        or TIME_PATTERN.match(line)
        or PERCENT_PATTERN.match(line)
        or SLIDE_PATTERN.match(line)
        or lowered_line in BADGE_LINES
        or lowered_line in NON_CUISINE_LINES
        or line.startswith("\u201c")
    )


def extract_price_range(lines: list[str]) -> str | None:
    for line in lines:
        match = PRICE_PATTERN.match(line)
        if match:
            return clean_spaces(match.group(1))
    return None


def extract_discount(lines: list[str]) -> str | None:
    for line in lines:
        if DISCOUNT_PATTERN.search(line):
            return line
    return None


def extract_photo_count(lines: list[str]) -> int | None:
    for line in lines:
        match = SLIDE_COUNT_PATTERN.match(line)
        if match:
            return int(match.group(1))
    return None


def extract_review_snippets(lines: list[str]) -> list[str]:
    snippets: list[str] = []
    for line in lines:
        if line.startswith(("\u201c", '"')) and 20 <= len(line) <= 260:
            snippets.append(line.strip('\u201c\u201d" '))
    return snippets[:3]


def deduplication_key(record: RestaurantRecord) -> str:
    if record.restaurant_url:
        return record.restaurant_url
    name = record.restaurant_name or ""
    address = record.address or ""
    return f"{name}|{address}".casefold()
