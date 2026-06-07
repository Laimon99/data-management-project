"""Pure cleaning / parsing functions for raw TheFork records.

No MongoDB, no network, no file I/O — every function takes and returns plain Python
values, so they are unit-testable in isolation. The strict EDA
(``services/extract/thefork_scraper/eda-report.md``) established that TheFork data is
already typed, already geocoded, duplicate-free, and 100% dining, so this module does
**parse + structure + flag**, not type-repair, geocoding, dedup, or relevance filtering.

The real work is resolving the dataset's First-Normal-Form violations: several rich
fields arrive as serialized structures or multi-value strings (``price_range`` = ``"30 €"``,
``cuisine_type`` = a comma-CSV, ``discount`` = free Italian promo text, opening hours as a
JSON string). The newer scraper additionally emits a pre-parsed ``working_hours_structured``;
this module prefers it and falls back to parsing the raw ``working_days_hours`` string.
"""

from __future__ import annotations

import json
import re
from typing import Any

_WS_RE = re.compile(r"\s+")
_TF_ID_RE = re.compile(r"-r(\d+)$")  # TheFork venue id token at the end of source_id
_INT_RE = re.compile(r"\d+")
_PCT_RE = re.compile(r"(\d{1,3})\s*%")
_CAP_RE = re.compile(r"\b(\d{5})\b")
_INTL_CAP_RE = re.compile(r"\bI-(\d{5})\b")  # international CAP prefix, e.g. I-20142
_EN_MILAN_RE = re.compile(r"\bMilan\b(?!o)")  # EN "Milan" but not "Milano"
_EN_ITALY_RE = re.compile(r"\bItaly\b")
_HOUSE_NUMBER_RE = re.compile(r"^\d")  # an address chunk that starts with a digit = civic no.
_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
# A `cuisine_type` value that looks like an address (CAP, "Milano", or a street prefix) is an
# upstream scraping leak — reject it rather than mint fake cuisine facets from it.
_CUISINE_ADDRESS_LEAK_RE = re.compile(
    r"\b\d{5}\b|\bMilano\b|"
    r"\b(?:Via|Viale|Corso|Piazza|Piazzale|Largo|Vicolo|Ripa|Alzaia|Foro|Bastioni)\b"
)

# Discount strings longer than this (or carrying a newline) are review text that bled into
# the field — the percentage in them is not a real promo, so it is discarded. (The
# 2026-06-06 scrape has zero such noisy values; this is a defensive guard for old/future
# data, exercised by synthetic fixtures.)
_DISCOUNT_MAX_LEN = 22

# Diet / religious cuisine tokens lifted out of `cuisine_type` into `dietary_options`,
# mapped to a canonical English tag. Matched case-insensitively.
DIETARY_TAGS = {
    "piatti vegetariani": "vegetarian",
    "vegetariano": "vegetarian",
    "piatti vegani": "vegan",
    "vegano": "vegan",
    "opzioni senza glutine": "gluten_free",
    "piatti biologici": "organic",
    "halal": "halal",
    "kosher": "kosher",
}

# Non-cuisine noise tokens that leaked into `cuisine_type` (a language note, not a cuisine).
NOISE_CUISINE_TOKENS = {"solo in italiano"}

# Italian -> canonical English weekday for the tidy opening-hours shape.
DAY_OF_WEEK = {
    "lunedì": "monday",
    "martedì": "tuesday",
    "mercoledì": "wednesday",
    "giovedì": "thursday",
    "venerdì": "friday",
    "sabato": "saturday",
    "domenica": "sunday",
}


def extract_tf_id(source_id: Any) -> str | None:
    """Extract TheFork's stable venue id (the trailing ``-r<n>`` token) from ``source_id``.

    e.g. ``"drinkiamo-bistrot-r801007"`` -> ``"801007"``. Unique per restaurant and stable
    across slug changes — a good join/blocking key for entity resolution. Returns ``None``
    when no token is found.
    """
    if source_id is None:
        return None
    match = _TF_ID_RE.search(str(source_id))
    return match.group(1) if match else None


def normalize_name(value: Any) -> str | None:
    """Trim, collapse internal whitespace, and recase ALL-CAPS names to title case.

    Mixed-case names are left as written; whitespace-only/``None`` -> ``None``.
    Title-casing is a best-effort display heuristic (``str.title()``); the raw name
    remains in ``restaurants_raw_thefork`` for audit.
    """
    if value is None:
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    if not cleaned:
        return None
    letters = [c for c in cleaned if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        cleaned = cleaned.title()
    return cleaned


def canonical_city(value: Any) -> str | None:
    """Canonicalize the city string: the constant EN ``"Milan"`` -> Italian ``"Milano"``."""
    if value is None:
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    if not cleaned:
        return None
    return "Milano" if cleaned.lower() == "milan" else cleaned


def normalize_address(value: Any) -> str | None:
    """Trim/collapse whitespace, strip the ``I-`` CAP prefix, fold EN ``Milan``/``Italy``.

    The normalized full string stays the source of truth; structured parts are a
    best-effort extraction on top (:func:`extract_address_parts`).
    """
    if value is None:
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    cleaned = _INTL_CAP_RE.sub(r"\1", cleaned)
    cleaned = _EN_MILAN_RE.sub("Milano", cleaned)
    cleaned = _EN_ITALY_RE.sub("Italia", cleaned)
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned).strip(" ,")
    return cleaned or None


def extract_address_parts(address: Any) -> dict[str, str | None]:
    """Best-effort split of the (normalized) address into street / house_number / postal_code.

    TheFork addresses are uniform (``"Via X, 13, Milano, 20142, Italia"``): the first comma
    chunk is the **street name**, the second (when it starts with a digit) is the **civic
    number**, and a 5-digit token is the CAP. Keeping ``street`` and ``house_number``
    separate avoids silently dropping the civic number from the structured address (the full
    normalized ``address`` remains the source of truth). Any part not confidently parsed is
    ``None``.
    """
    parts: dict[str, str | None] = {"street": None, "house_number": None, "postal_code": None}
    if not address:
        return parts
    text = str(address)
    cap = _CAP_RE.search(text)
    if cap:
        parts["postal_code"] = cap.group(1)
    chunks = [c.strip() for c in text.split(",")]
    if chunks and chunks[0]:
        parts["street"] = chunks[0]
    if len(chunks) > 1 and _HOUSE_NUMBER_RE.match(chunks[1]):
        parts["house_number"] = chunks[1]
    return parts


def parse_avg_price_eur(value: Any) -> int | None:
    """Parse the average-price euro string (``"30 €"``) into an int. ``"1 €"`` -> ``1``."""
    if value is None:
        return None
    match = _INT_RE.search(str(value))
    return int(match.group(0)) if match else None


def has_discount(value: Any) -> bool:
    """True when a non-empty promo string was scraped (independent of parseability)."""
    return isinstance(value, str) and bool(value.strip())


def parse_discount_pct(value: Any) -> int | None:
    """Extract the promo percentage from a clean ``discount`` string, else ``None``.

    Clean promo strings (``"sconto -20%"``, ``"Sconti fino al 20%"``) yield the integer
    percent. Strings that are review text bled into the field (newline, over-long, or
    carrying multiple distinct percentages) are treated as noise and return ``None`` —
    a percent scraped out of a review sentence is not a real discount.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "\n" in text or "\\n" in text or len(text) > _DISCOUNT_MAX_LEN:
        return None
    pcts = {int(m) for m in _PCT_RE.findall(text)}
    if len(pcts) != 1:
        return None
    pct = next(iter(pcts))
    return pct if 0 < pct <= 100 else None


def split_cuisines(value: Any) -> tuple[list[str], list[str]]:
    """Split the comma-CSV ``cuisine_type`` into (cuisines, dietary_options).

    Diet/religious tags (vegetarian / vegan / gluten-free / organic / halal / kosher) are
    lifted into ``dietary_options`` (canonical English, de-duplicated); the language-note
    noise token ``"Solo in Italiano"`` is dropped; everything else is a cuisine (order
    preserved, de-duplicated case-insensitively).
    """
    if not isinstance(value, str):
        return [], []
    cuisines: list[str] = []
    dietary: list[str] = []
    seen_cuisine: set[str] = set()
    seen_dietary: set[str] = set()
    for token in value.split(","):
        tok = _WS_RE.sub(" ", token).strip()
        if not tok:
            continue
        low = tok.lower()
        if low in NOISE_CUISINE_TOKENS:
            continue
        if low in DIETARY_TAGS:
            tag = DIETARY_TAGS[low]
            if tag not in seen_dietary:
                seen_dietary.add(tag)
                dietary.append(tag)
        elif low not in seen_cuisine:
            seen_cuisine.add(low)
            cuisines.append(tok)
    return cuisines, dietary


def is_cuisine_address_leak(value: Any) -> bool:
    """True when ``cuisine_type`` actually holds an address (an upstream scraper leak).

    e.g. ``"Corso Garibaldi, 111, Milano"`` — splitting it would mint three fake cuisine
    facets. Such fields are rejected (``cuisines = []``) and flagged ``invalid_cuisine_type``.
    """
    return isinstance(value, str) and bool(_CUISINE_ADDRESS_LEAK_RE.search(value))


def _normalize_clock(value: Any) -> tuple[Any, bool]:
    """Normalize a ``HH:MM`` time, folding past-midnight notation into the next day.

    TheFork writes late closings as ``"24:00"``–``"29:00"`` (hours past midnight). Those are
    not valid clock times, so they are folded to ``00:00``–``05:00`` with a ``next_day``
    flag. Returns ``(normalized, next_day)``; an unparseable value is returned unchanged with
    ``next_day = False``.
    """
    if not isinstance(value, str):
        return value, False
    match = _CLOCK_RE.match(value.strip())
    if not match:
        return value, False
    hour, minute = int(match.group(1)), int(match.group(2))
    next_day = hour >= 24
    if next_day:
        hour -= 24
    return f"{hour:02d}:{minute:02d}", next_day


def tidy_opening_hours(structured: Any, raw_string: Any) -> list[dict[str, Any]]:
    """Reshape opening hours into a tidy ``[{day, opens, closes}]`` list.

    Prefers the pre-parsed ``working_hours_structured`` (a list of schema.org
    ``OpeningHoursSpecification`` objects emitted by the newer scraper); falls back to
    ``json.loads`` of the raw ``working_days_hours`` string when the structured field is
    absent. Day names are mapped to canonical English; one entry is emitted per day in a
    spec's ``dayOfWeek`` list, preserving split (e.g. lunch/dinner) shifts. Past-midnight
    times (``"24:00"``–``"29:00"``) are folded to valid ``HH:MM`` with ``closes_next_day``
    set, so every emitted ``opens``/``closes`` is a real clock time. Malformed or empty
    input -> ``[]``.
    """
    specs: Any = None
    if isinstance(structured, list) and structured:
        specs = structured
    elif isinstance(raw_string, str) and raw_string.strip():
        try:
            specs = json.loads(raw_string)
        except (ValueError, TypeError):
            specs = None
    if not isinstance(specs, list):
        return []

    out: list[dict[str, Any]] = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        opens = spec.get("opens")
        closes = spec.get("closes")
        days = spec.get("dayOfWeek") or []
        if isinstance(days, str):
            days = [days]
        opens_norm, opens_next_day = _normalize_clock(opens)
        closes_norm, closes_next_day = _normalize_clock(closes)
        for day in days:
            key = str(day).strip().lower()
            entry: dict[str, Any] = {
                "day": DAY_OF_WEEK.get(key, key),
                "opens": opens_norm,
                "closes": closes_norm,
            }
            if closes_next_day or opens_next_day:
                entry["closes_next_day"] = True
            out.append(entry)
    return out


def slim_reviews(reviews: Any, cap: int = 15) -> list[dict[str, Any]]:
    """Project reviews to ``{author_name, rating, text, date}`` (drops the always-null title).

    Keeps up to ``cap`` reviews (the newer scraper raised the per-restaurant cap from 5 to
    15). Per-review ``rating`` stays on TheFork's native 0–10 scale. The full reviews
    remain in ``restaurants_raw_thefork`` for the optional LLM text-extraction extension.
    """
    if not isinstance(reviews, list):
        return []
    slimmed: list[dict[str, Any]] = []
    for review in reviews[:cap]:
        if not isinstance(review, dict):
            continue
        slimmed.append(
            {
                "author_name": review.get("author_name"),
                "rating": review.get("rating"),
                "text": review.get("text"),
                "date": review.get("date"),
            }
        )
    return slimmed


def sample_avg_rating(reviews: Any) -> float | None:
    """Mean of the nested-review ratings (a SAMPLE signal — never the platform average).

    The nested reviews are a recent, capped sample (≤15), so this is a quality cross-check,
    not a stand-in for the platform ``rating``. Returns ``None`` when no review carries a
    numeric rating.
    """
    if not isinstance(reviews, list):
        return None
    ratings = [
        float(r["rating"])
        for r in reviews
        if isinstance(r, dict)
        and isinstance(r.get("rating"), (int, float))
        and not isinstance(r.get("rating"), bool)
    ]
    if not ratings:
        return None
    return round(sum(ratings) / len(ratings), 2)


def _coerce_rating(value: Any) -> float | None:
    """Pass through a numeric rating in TheFork's native ``[0, 10]``; else ``None``.

    TheFork data is already typed (EDA), so this is a defensive guard, not a parser.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    rating = float(value)
    return rating if 0.0 <= rating <= 10.0 else None


def _coerce_count(value: Any) -> int | None:
    """Pass through a non-negative integer review count; else ``None``.

    Accepts whole-valued floats (e.g. ``200.0``); non-integer floats and other types ->
    ``None``. ``review_count`` is best-effort (the scrape may not capture every review).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    count = int(value)
    return count if count >= 0 else None


def clean_record(
    raw: dict[str, Any], *, low_review_threshold: int = 10, review_cap: int = 15
) -> dict[str, Any]:
    """Clean one raw TheFork record into a lean clean document (pure).

    Parses the 1NF-violation fields (price, discount, cuisine, hours), normalizes name /
    address / city, lifts ``tf_id`` and structured address parts, slims reviews, and
    derives count-only quality flags plus clearly sample-labeled review features. Drops the
    dead fields (``phone_number`` / ``email`` / ``website`` / ``social_links``) and the
    raw serialized strings (replaced by parsed fields). Coordinates and the native 0–10
    ``rating`` are copied verbatim. Does not set ``_id`` — that is the transform layer's
    job. Null ``rating`` is **not** backfilled from the nested-review sample (biased).
    """
    raw_discount = raw.get("discount")
    raw_cuisine = raw.get("cuisine_type")
    rating = _coerce_rating(raw.get("rating"))
    review_count = _coerce_count(raw.get("review_count"))
    cuisine_leak = is_cuisine_address_leak(raw_cuisine)
    cuisines, dietary_options = ([], []) if cuisine_leak else split_cuisines(raw_cuisine)
    address = normalize_address(raw.get("address"))
    parts = extract_address_parts(address)
    opening_hours = tidy_opening_hours(
        raw.get("working_hours_structured"), raw.get("working_days_hours")
    )
    reviews = slim_reviews(raw.get("reviews"), cap=review_cap)
    samp_avg = sample_avg_rating(reviews)

    has_rating = rating is not None
    missing_review_count = review_count is None
    low_review = review_count is not None and review_count < low_review_threshold
    rating_sample_divergent = (
        rating is not None and samp_avg is not None and abs(rating - samp_avg) > 1.0
    )

    flags: list[str] = []
    if not has_rating:
        flags.append("no_rating")
    if missing_review_count:
        flags.append("missing_review_count")
    if low_review:
        flags.append("low_review")
    if rating_sample_divergent:
        flags.append("rating_sample_divergent")
    if cuisine_leak:
        flags.append("invalid_cuisine_type")

    return {
        "source": raw.get("source"),
        "source_id": raw.get("source_id"),
        "tf_id": extract_tf_id(raw.get("source_id")),
        "restaurant_url": raw.get("restaurant_url"),
        "restaurant_name": normalize_name(raw.get("restaurant_name")),
        "latitude": raw.get("latitude"),
        "longitude": raw.get("longitude"),
        "address": address,
        "street": parts["street"],
        "house_number": parts["house_number"],
        "postal_code": parts["postal_code"],
        "city": canonical_city(raw.get("city")),
        "rating": rating,
        "review_count": review_count,
        "has_rating": has_rating,
        "has_review_count": not missing_review_count,
        "low_review": low_review,
        "avg_price_eur": parse_avg_price_eur(raw.get("price_range")),
        "discount_pct": parse_discount_pct(raw_discount),
        "has_discount": has_discount(raw_discount),
        "cuisines": cuisines,
        "dietary_options": dietary_options,
        "opening_hours": opening_hours,
        "has_hours": bool(opening_hours),
        "photo_count": raw.get("photo_count"),
        "reviews": reviews,
        "review_snippets": raw.get("review_snippets") or [],
        "sample_size": len(reviews),
        "sample_avg_rating": samp_avg,
        "rating_sample_divergent": rating_sample_divergent,
        "has_reviews": bool(reviews),
        "scraped_at": raw.get("scraped_at"),
        "source_page_number": raw.get("source_page_number"),
        "detail_scraped": raw.get("detail_scraped"),
        "flags": flags,
    }
