from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from .models import RestaurantRecord


TRIPADVISOR_BASE_URL = "https://www.tripadvisor.it"
RESTAURANT_PATH_PATTERN = re.compile(
    r"/Restaurant_Review-g187849-d\d+-Reviews-[^/?#]+\.html",
    re.IGNORECASE,
)
SOURCE_ID_PATTERN = re.compile(r"-d(\d+)-", re.IGNORECASE)
RANKING_PREFIX_PATTERN = re.compile(r"^\s*(?:#?\d+[\).]\s+|\d+\s+)")
RATING_PATTERN = re.compile(r"\b([0-5][,.][0-9])\b")
REVIEW_COUNT_PATTERN = re.compile(
    r"\(?\s*([\d.,\s]+)\s+(?:reviews?|recensioni)\s*\)?",
    re.IGNORECASE,
)
PHOTO_COUNT_PATTERN = re.compile(r"\(?\s*([\d.,\s]+)\s+(?:photos?|foto)\s*\)?", re.IGNORECASE)
EURO_TOKEN_PATTERN = r"(?:\u20ac|\u00e2\u201a\u00ac|\u00c3\u00a2\u00e2\u20ac\u0161\u00c2\u00ac)"
PRICE_RANGE_PATTERN = re.compile(
    rf"(\${{1,4}}(?:\s*-\s*\${{1,4}})?|{EURO_TOKEN_PATTERN}{{1,4}}(?:\s*-\s*{EURO_TOKEN_PATTERN}{{1,4}})?)"
)
ADDRESS_HINT_PATTERN = re.compile(
    r"\b(?:via|viale|piazza|corso|largo|vicolo|alzaia|foro|ripa|strada|bastioni)\b",
    re.IGNORECASE,
)

NON_NAME_LINES = {
    "sponsorizzato",
    "sponsored",
    "aperto ora",
    "chiuso ora",
    "open now",
    "closed now",
    "michelin",
}

NON_CUISINE_LINES = {
    "aperto ora",
    "chiuso ora",
    "open now",
    "closed now",
    "ordina online",
    "prenota",
    "reserve",
    "order online",
}


def parse_restaurant_card(
    restaurant_url: str,
    card_text: str,
    link_text: str | None,
    aria_label: str | None,
    scraped_at: str,
    source_page_number: int,
) -> RestaurantRecord | None:
    normalized_url = normalize_restaurant_url(restaurant_url)
    if normalized_url is None:
        return None

    lines = split_visible_lines(card_text)
    name = extract_restaurant_name(lines, link_text, aria_label)
    if not name:
        name = extract_name_from_url(normalized_url)
    cuisine_type, price_range = extract_cuisine_and_price(lines)

    return RestaurantRecord(
        source_id=extract_source_id(normalized_url),
        restaurant_name=name,
        address=extract_address(lines),
        rating=extract_rating(lines),
        review_count=extract_review_count(lines),
        cuisine_type=cuisine_type,
        price_range=price_range,
        photo_count=extract_photo_count(lines),
        restaurant_url=normalized_url,
        review_snippets=extract_review_snippets(lines),
        scraped_at=scraped_at,
        source_page_number=source_page_number,
    )


def normalize_restaurant_url(raw_url: str) -> str | None:
    absolute_url = urljoin(TRIPADVISOR_BASE_URL, raw_url)
    parsed_url = urlsplit(absolute_url)
    if not RESTAURANT_PATH_PATTERN.search(parsed_url.path):
        return None
    return urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", ""))


def extract_source_id(restaurant_url: str) -> str | None:
    match = SOURCE_ID_PATTERN.search(urlsplit(restaurant_url).path)
    if match:
        return f"d{match.group(1)}"
    slug = urlsplit(restaurant_url).path.rsplit("/", maxsplit=1)[-1]
    return slug.removesuffix(".html") or None


def extract_name_from_url(restaurant_url: str) -> str | None:
    path = urlsplit(restaurant_url).path
    match = re.search(r"-Reviews-([^-]+)-Milan_Lombardy\.html$", path, re.IGNORECASE)
    if not match:
        return None
    raw_name = match.group(1).replace("_", " ")
    cleaned_name = clean_spaces(raw_name)
    return cleaned_name or None


def split_visible_lines(text: str) -> list[str]:
    normalized_text = text.replace("\r", "\n").replace("\u00a0", " ").replace("\u202f", " ")
    lines: list[str] = []
    for raw_line in normalized_text.split("\n"):
        cleaned_line = clean_spaces(raw_line)
        if cleaned_line:
            lines.append(cleaned_line)
    if len(lines) <= 1:
        return split_compact_card_text(text)
    return lines


def split_compact_card_text(text: str) -> list[str]:
    cleaned_text = clean_spaces(text.replace("\u00a0", " ").replace("\u202f", " "))
    if not cleaned_text:
        return []

    markers = [
        r"(?=\b[0-5][,.][0-9]\b)",
        r"(?=\(\s*[\d.,\s]+\s+(?:reviews?|recensioni)\s*\))",
        r"(?=\b(?:Open now|Closed now|Aperto ora|Chiuso ora)\b)",
    ]
    pattern = "|".join(markers)
    parts = [clean_spaces(part) for part in re.split(pattern, cleaned_text) if clean_spaces(part)]
    return parts or [cleaned_text]


def clean_spaces(text: str) -> str:
    text = normalize_text_artifacts_ascii(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_text_artifacts_ascii(text: str) -> str:
    replacements = {
        "\u00e2\u201a\u00ac": "\u20ac",
        "\u00c3\u00a2\u00e2\u20ac\u0161\u00c2\u00ac": "\u20ac",
        "\u00e2\u20ac\u00a2": " ",
        "\u00e2\u20ac\u201c": "-",
        "\u00e2\u20ac\u201d": "-",
        "\u00e2\u20ac\u02dc": "'",
        "\u00e2\u20ac\u2122": "'",
        "\u00e2\u20ac\u0153": '"',
        "\u00e2\u20ac\ufffd": '"',
    }
    for source, replacement in replacements.items():
        text = text.replace(source, replacement)
    return text


def extract_restaurant_name(
    lines: list[str],
    link_text: str | None,
    aria_label: str | None,
) -> str | None:
    candidates = [link_text, aria_label, *lines]
    for raw_candidate in candidates:
        candidate = normalize_name_candidate(raw_candidate)
        if candidate:
            return candidate
    return None


def normalize_name_candidate(text: str | None) -> str | None:
    if text is None:
        return None
    candidate = clean_spaces(text)
    if not candidate:
        return None
    candidate = re.sub(r"^Ristorante\s+", "", candidate, flags=re.IGNORECASE)
    candidate = RANKING_PREFIX_PATTERN.sub("", candidate).strip()
    if not candidate:
        return None
    lowered_candidate = candidate.lower()
    if lowered_candidate in NON_NAME_LINES:
        return None
    if re.search(r"\b(?:sconto|discount|off)\b", lowered_candidate) and re.search(r"\d+\s*%", candidate):
        return None
    if candidate.startswith("-") or candidate.startswith("%"):
        return None
    if is_rating_line(candidate) or is_review_count_line(candidate):
        return None
    if PRICE_RANGE_PATTERN.fullmatch(candidate):
        return None
    if PRICE_RANGE_PATTERN.search(candidate) and not re.search(r"[A-Za-zÀ-ÿ]{3,}", candidate):
        return None
    if len(candidate) > 120:
        return None
    return candidate


def extract_rating(lines: list[str]) -> float | None:
    for line in lines:
        if is_review_count_line(line):
            continue
        match = RATING_PATTERN.search(line)
        if match:
            value = float(match.group(1).replace(",", "."))
            if 0 <= value <= 5:
                return value
    return None


def is_rating_line(line: str) -> bool:
    return RATING_PATTERN.search(line) is not None


def extract_review_count(lines: list[str]) -> int | None:
    for line in lines:
        match = REVIEW_COUNT_PATTERN.search(line)
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            if digits:
                return int(digits)
    return None


def is_review_count_line(line: str) -> bool:
    return REVIEW_COUNT_PATTERN.search(line) is not None


def extract_cuisine_and_price(lines: list[str]) -> tuple[str | None, str | None]:
    for line in lines:
        candidate = clean_spaces(line)
        if not is_cuisine_or_price_candidate(candidate):
            continue
        split_result = split_cuisine_price(candidate)
        if split_result != (None, None):
            return split_result
    return None, None


def split_cuisine_price(text: str) -> tuple[str | None, str | None]:
    price_match = PRICE_RANGE_PATTERN.search(text)
    if price_match:
        price_range = clean_spaces(price_match.group(1))
        cuisine_type = clean_cuisine_text(text[: price_match.start()])
        if not cuisine_type:
            cuisine_type = clean_cuisine_text(text[price_match.end() :])
        return cuisine_type or None, price_range or None

    if looks_like_cuisine(text):
        return text, None
    return None, None


def is_cuisine_or_price_candidate(line: str) -> bool:
    lowered_line = line.lower()
    if lowered_line in NON_CUISINE_LINES:
        return False
    if normalize_name_candidate(line) == line and RANKING_PREFIX_PATTERN.match(line):
        return False
    if is_review_count_line(line) or is_rating_line(line):
        return False
    if line.startswith('"') or line.startswith("\u201c"):
        return False
    return PRICE_RANGE_PATTERN.search(line) is not None or looks_like_cuisine(line)


def looks_like_cuisine(text: str) -> bool:
    if len(text) > 90:
        return False
    if any(char.isdigit() for char in text):
        return False
    lowered_text = text.lower()
    if lowered_text in NON_CUISINE_LINES:
        return False
    if ADDRESS_HINT_PATTERN.search(text):
        return False
    cuisine_keywords = [
        "italian",
        "italiana",
        "lombard",
        "mediterranean",
        "japanese",
        "asian",
        "european",
        "seafood",
        "pizza",
        "sushi",
        "american",
        "barbecue",
        "steakhouse",
        "fusion",
        "cinese",
        "giapponese",
        "mediterranea",
        "pesce",
        "lombarda",
        "europea",
        "asiatica",
    ]
    return "," in text or any(keyword in lowered_text for keyword in cuisine_keywords)


def clean_cuisine_text(text: str) -> str | None:
    cleaned_text = clean_spaces(text)
    cleaned_text = cleaned_text.strip("•|-–—,; ")
    return cleaned_text or None


def extract_address(lines: list[str]) -> str | None:
    for line in lines:
        if ADDRESS_HINT_PATTERN.search(line) and not is_review_count_line(line):
            return line
    return None


def extract_photo_count(lines: list[str]) -> int | None:
    for line in lines:
        match = PHOTO_COUNT_PATTERN.search(line)
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            if digits:
                return int(digits)
    return None


def extract_review_snippets(lines: list[str]) -> list[str]:
    snippets: list[str] = []
    for line in lines:
        if line.startswith(("\u201c", '"')) and 20 <= len(line) <= 280:
            snippets.append(line.strip("\u201c\u201d\" "))
    return snippets[:3]


def deduplication_key(record: RestaurantRecord) -> str:
    if record.restaurant_url:
        return record.restaurant_url
    if record.restaurant_name and record.address:
        return f"{record.restaurant_name}|{record.address}".casefold()
    return f"{record.restaurant_name or ''}|{record.source_page_number}".casefold()
