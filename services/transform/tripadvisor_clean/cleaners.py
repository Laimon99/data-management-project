"""Pure cleaning / parsing functions for raw Tripadvisor records.

No MongoDB, no network, no file I/O — every function takes and returns plain
Python values, so they are unit-testable in isolation and reusable by the other
sources later. Sentinel/`NaN` semantics are shared with ``geocode.is_nan`` to
keep a single definition.

Beyond the original type-repair (Italian decimal-comma ``rating``, ``"(1.234
recensioni)"`` review counts, ``"NaN"`` sentinels) this module now parses the rich
fields TripAdvisor ships as raw strings — ``number_photo_uploaded``, ``price_range``,
``cuisine_type``, ``working_days_hours``, ``review`` — into structured features, and
derives the per-record quality flags that bring this transform to parity with
``google_clean`` and ``thefork_clean``. See ``clean-dataset-schema.md`` for the output
shape and ``drop-policy.md`` for why the layer is flag-first (no default drops).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from transform.common.contacts import normalize_phone, normalize_website

from .geocode import is_nan

_WS_RE = re.compile(r"\s+")
_LOCATION_ID_RE = re.compile(r"-d(\d+)-")  # TripAdvisor location id token in the URL
_CAP_RE = re.compile(r"\b(\d{5})\b")  # Italian postal code (CAP)
_RATING_RE = re.compile(r"\d+(?:\.\d+)?")
_INT_TOKEN_RE = re.compile(r"\d[\d.]*")  # an integer possibly with Italian thousands dots
_COUNTRY_RE = re.compile(r"\b(italia|italy)\b", re.IGNORECASE)

# --- price ----------------------------------------------------------------------------
# TripAdvisor ships only four price values: "€", "€€-€€€", "€€€€", and "NaN". The euro
# count of the lower bound is a clean ordinal tier; anything outside the {€, -} alphabet
# is treated as unparseable rather than coerced into a fake tier.

# --- cuisines / opening hours ---------------------------------------------------------
# Italian weekday -> canonical English (shared output vocabulary with thefork_clean's
# tidy opening-hours shape). Accent-tolerant lookups are added programmatically below.
DAY_OF_WEEK_IT = {
    "lunedì": "monday",
    "martedì": "tuesday",
    "mercoledì": "wednesday",
    "giovedì": "thursday",
    "venerdì": "friday",
    "sabato": "saturday",
    "domenica": "sunday",
}
# Also accept the accent-stripped spellings ("lunedi", ...) the scrape occasionally emits.
DAY_OF_WEEK_IT.update({k.replace("ì", "i"): v for k, v in list(DAY_OF_WEEK_IT.items()) if "ì" in k})
_DAY_TOKEN_RE = re.compile(
    r"(luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica)",
    re.IGNORECASE,
)
# A single opening shift: "2.00-10.30", "12.00-15.00", "12.00-1.00" (dots or colons).
_SHIFT_RE = re.compile(r"^(\d{1,2})[.:](\d{2})-(\d{1,2})[.:](\d{2})$")
# Day/shift connector: TripAdvisor uses " and " between *both* days and shifts, plus a
# ":" after the first day name. Split content on either.
_HOURS_SPLIT_RE = re.compile(r"\band\b|:", re.IGNORECASE)

# --- reviews --------------------------------------------------------------------------
# The repeated display suffix glued onto truncated review text (Italian "read more"),
# plus defensive English/alt variants. Stripped without touching real review text.
_READ_MORE_SUFFIXES = ("Scopri di più", "Leggi tutto", "Read more", "Altro")
_IT_MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}
_IT_DATE_RE = re.compile(r"^(\d{1,2})\s+([A-Za-zàèéìòù]+)\s+(\d{4})$")


def nan_to_none(value: Any) -> Any:
    """Coerce the ``"NaN"`` sentinel / empty / None to a real ``None``."""
    return None if is_nan(value) else value


def parse_rating(value: Any) -> float | None:
    """Parse an Italian decimal-comma rating (e.g. ``"5,0"``) into a float.

    Accepts an already-numeric value and defensively a decimal-point string.
    Out-of-range (outside ``[0, 5]``) or unparseable values become ``None``.
    """
    if is_nan(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        rating = float(value)
    else:
        match = _RATING_RE.search(str(value).strip().replace(",", "."))
        if not match:
            return None
        try:
            rating = float(match.group(0))
        except ValueError:
            return None
    return rating if 0.0 <= rating <= 5.0 else None


def parse_review_count(value: Any) -> int | None:
    """Extract the integer review count from strings like ``"(1.234 recensioni)"``.

    Drops Italian thousands separators. Unparseable values become ``None``. Also reused
    for the per-review ``number_of_contribution`` string (``"875"`` -> ``875``).
    """
    if is_nan(value):
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    match = _INT_TOKEN_RE.search(str(value))
    if not match:
        return None
    digits = match.group(0).replace(".", "")
    return int(digits) if digits.isdigit() else None


def parse_photo_count(value: Any) -> int | None:
    """Parse ``number_photo_uploaded`` into a non-negative int.

    Accepts plain integer strings and values with Italian thousands separators
    (``"1.234"`` -> ``1234``). ``NaN`` / blank / unparseable -> ``None``.
    """
    if is_nan(value):
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 0 else None
    match = _INT_TOKEN_RE.search(str(value))
    if not match:
        return None
    digits = match.group(0).replace(".", "")
    return int(digits) if digits.isdigit() else None


def parse_price(value: Any) -> tuple[str | None, int | None]:
    """Parse ``price_range`` into ``(price_band, price_tier_level)``.

    ``price_band`` keeps the source euro-symbol label (``"€"``, ``"€€-€€€"``, ``"€€€€"``);
    ``price_tier_level`` is the euro count of the band's lower bound (1..4). Anything
    outside the ``{€, -}`` alphabet (free text, ``NaN``) is not a valid tier ->
    ``(None, None)``.
    """
    if is_nan(value):
        return None, None
    band = str(value).strip()
    if not band or set(band) - {"€", "-"}:
        return None, None
    level = band.split("-")[0].count("€")
    return (band, level) if level else (None, None)


def split_cuisines(value: Any) -> list[str]:
    """Split the comma-CSV ``cuisine_type`` into a list of cuisine tokens.

    Trims tokens, drops empties, preserves the source vocabulary and original language,
    and de-duplicates case-insensitively while keeping first-seen order. ``NaN`` /
    missing / non-string -> ``[]``.
    """
    if is_nan(value) or not isinstance(value, str):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for token in value.split(","):
        tok = _WS_RE.sub(" ", token).strip()
        if not tok:
            continue
        low = tok.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(tok)
    return out


def _parse_shift(token: str) -> tuple[str, str, bool] | None:
    """Parse one ``"H.MM-H.MM"`` shift into ``(opens, closes, closes_next_day)``.

    Times are zero-padded to ``HH:MM``. A close that is not after the open (e.g.
    ``"12.00-1.00"``) is a past-midnight closing -> ``closes_next_day = True``.
    Unparseable / out-of-range -> ``None`` (so ``Chiuso`` and noise emit nothing).
    """
    match = _SHIFT_RE.match(token.strip())
    if not match:
        return None
    oh, om, ch, cm = (int(g) for g in match.groups())
    if not (0 <= oh <= 23 and 0 <= om <= 59 and 0 <= ch <= 23 and 0 <= cm <= 59):
        return None
    opens = f"{oh:02d}:{om:02d}"
    closes = f"{ch:02d}:{cm:02d}"
    closes_next_day = (ch * 60 + cm) <= (oh * 60 + om)
    return opens, closes, closes_next_day


def parse_opening_hours(value: Any) -> list[dict[str, Any]]:
    """Parse the flattened ``working_days_hours`` string into a tidy list.

    TripAdvisor flattens the weekly table into one string where ``" and "`` separates
    *both* days and shifts and only the first day carries a ``":"`` (e.g.
    ``"Domenica: Chiuso and Lunedì and 12.00-15.00 and 19.00-23.00 and Martedì and ..."``).
    The parser is conservative: it splits on the seven Italian weekday tokens, then emits
    one ``{day, opens, closes}`` entry per confidently parsed shift (split shifts kept as
    separate entries, English day names, ``closes_next_day`` for past-midnight closings).
    ``Chiuso`` days and malformed/missing input emit nothing -> ``[]`` (never ``None``).
    """
    if is_nan(value) or not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    markers = list(_DAY_TOKEN_RE.finditer(text))
    if not markers:
        return []
    out: list[dict[str, Any]] = []
    for i, marker in enumerate(markers):
        day = DAY_OF_WEEK_IT.get(marker.group(1).lower())
        if day is None:
            continue
        start = marker.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        for token in _HOURS_SPLIT_RE.split(text[start:end]):
            shift = _parse_shift(token.strip())
            if shift is None:
                continue
            opens, closes, closes_next_day = shift
            entry: dict[str, Any] = {"day": day, "opens": opens, "closes": closes}
            if closes_next_day:
                entry["closes_next_day"] = True
            out.append(entry)
    return out


def parse_review_date(value: Any) -> str | None:
    """Parse an Italian review date (``"29 maggio 2026"``) into an ISO date string.

    Returns ``"2026-05-29"``; unknown month / malformed / ``NaN`` -> ``None``.
    """
    if is_nan(value) or not isinstance(value, str):
        return None
    match = _IT_DATE_RE.match(value.strip())
    if not match:
        return None
    month = _IT_MONTHS.get(match.group(2).lower())
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1))).isoformat()
    except ValueError:
        return None


def _strip_read_more(text: Any) -> str | None:
    """Remove the trailing display read-more suffix from review text; blank -> ``None``."""
    cleaned = nan_to_none(text)
    if not isinstance(cleaned, str):
        return cleaned
    cleaned = cleaned.strip()
    for suffix in _READ_MORE_SUFFIXES:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].rstrip()
            break
    return cleaned or None


def slim_reviews(reviews: Any, cap: int = 20) -> list[dict[str, Any]]:
    """Project nested reviews to the analytically useful fields, capped at ``cap``.

    Keeps the first ``cap`` reviews (scrape order ≈ recency) as
    ``{nickname, contributions, title, text, date}``: author nickname, parsed author
    contribution count, title, read-more-stripped text, and ISO publication date. The
    full reviews remain in ``restaurants_raw_tripadvisor`` for the optional LLM
    text-extraction extension. ``"NaN"`` / non-list -> ``[]``.
    """
    if not isinstance(reviews, list):
        return []
    slimmed: list[dict[str, Any]] = []
    for review in reviews[:cap]:
        if not isinstance(review, dict):
            continue
        author = review.get("author") or {}
        slimmed.append(
            {
                "nickname": nan_to_none(author.get("nickname")),
                "contributions": parse_review_count(author.get("number_of_contribution")),
                "title": nan_to_none(review.get("title")),
                "text": _strip_read_more(review.get("text")),
                "date": parse_review_date(review.get("date_of_publication")),
            }
        )
    return slimmed


def extract_location_id(source_url: Any) -> str | None:
    """Extract TripAdvisor's stable location id (the ``-d<n>-`` token) from the URL.

    e.g. ``…-d28119476-Reviews-…`` -> ``"28119476"``. This is TripAdvisor's canonical
    venue id — unique per restaurant, stable across slug/locale changes — so it is a
    good join/blocking key for entity resolution. Returns ``None`` if no token is found.
    The collection ``_id`` remains ``source_url``; this is stored as a regular field.
    """
    if is_nan(source_url):
        return None
    match = _LOCATION_ID_RE.search(str(source_url))
    return match.group(1) if match else None


def normalize_name(value: Any) -> str | None:
    """Trim and collapse internal whitespace; whitespace-only/`NaN` -> None."""
    if is_nan(value):
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    return cleaned or None


def normalize_address(value: Any) -> str | None:
    """Trim, collapse whitespace, and standardize comma separators."""
    if is_nan(value):
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned).strip(" ,")
    return cleaned or None


def clean_optional_text(value: Any) -> str | None:
    """Normalize an optional contact string (website/phone/email); ``NaN``/blank -> None."""
    if is_nan(value):
        return None
    cleaned = _WS_RE.sub(" ", str(value)).strip()
    return cleaned or None


def extract_address_parts(value: Any) -> dict[str, str | None]:
    """Best-effort structured extraction of postal_code / street / house_number / city.

    Conservative: any sub-field that cannot be confidently parsed is ``None``.
    The normalized full ``address`` remains the source of truth.
    """
    parts: dict[str, str | None] = {
        "postal_code": None,
        "street": None,
        "house_number": None,
        "city": None,
    }
    text = normalize_address(value)
    if not text:
        return parts

    def split_street_house_number(prefix: str) -> tuple[str | None, str | None]:
        tokens = prefix.strip().strip(",").split()
        for idx, token in enumerate(tokens):
            cleaned_token = token.strip(" ,")
            if cleaned_token and cleaned_token[0].isdigit():
                street = " ".join(tokens[:idx]).strip().strip(",").strip()
                return street or None, cleaned_token
        street = prefix.strip().strip(",").strip()
        return street or None, None

    cap = _CAP_RE.search(text)
    if cap:
        parts["postal_code"] = cap.group(1)
        street_prefix = text[: cap.start()].strip().rstrip(",").strip()
        parts["street"], parts["house_number"] = split_street_house_number(street_prefix)
        tail = text[cap.end() :].strip().lstrip(",").strip()
        if tail:
            city = tail.split(",")[0]
            city = _COUNTRY_RE.sub("", city).strip(" ,")
            parts["city"] = city or None
    else:
        # No CAP found: best-effort street = first comma-separated chunk.
        parts["street"], parts["house_number"] = split_street_house_number(text.split(",")[0])
    return parts


def clean_record(
    raw: dict[str, Any], *, low_review_threshold: int = 10, review_cap: int = 20
) -> dict[str, Any]:
    """Clean one raw Tripadvisor record into a structured clean document (pure).

    Type-repairs ``rating`` / ``total_review``, normalizes name / address / contacts,
    lifts ``ta_location_id`` and structured address parts, and parses the rich raw
    strings (``number_photo_uploaded`` -> ``photo_count``, ``price_range`` ->
    ``price_band`` / ``price_tier_level``, ``cuisine_type`` -> ``cuisines``,
    ``working_days_hours`` -> ``opening_hours``, ``review`` -> capped ``reviews``). The
    replaced raw fields are **dropped** (the raw collection stays the audit trail).
    Derives count-only quality flags and ``has_*`` booleans; coordinate-derived flags
    (``has_coordinates`` / ``geocode_not_found`` / ``missing_coordinates``) are added by
    the transform layer after geocoding. Does not set ``_id``.
    """
    name = normalize_name(raw.get("restaurant_name"))
    address = normalize_address(raw.get("address"))
    parts = extract_address_parts(raw.get("address"))
    rating = parse_rating(raw.get("rating"))
    total_review = parse_review_count(raw.get("total_review"))
    price_band, price_tier_level = parse_price(raw.get("price_range"))
    cuisines = split_cuisines(raw.get("cuisine_type"))
    opening_hours = parse_opening_hours(raw.get("working_days_hours"))
    reviews = slim_reviews(raw.get("review"), cap=review_cap)
    website = clean_optional_text(raw.get("website"))
    phone = clean_optional_text(raw.get("phone_number"))
    email = clean_optional_text(raw.get("email"))
    website = normalize_website(website)
    phone = normalize_phone(phone)

    has_rating = rating is not None
    has_review_count = total_review is not None
    low_review = total_review is not None and total_review < low_review_threshold
    has_address = address is not None
    has_reviews = bool(reviews)
    has_hours = bool(opening_hours)
    has_phone = phone is not None
    has_website = website is not None
    has_email = email is not None
    rating_with_zero_reviews = rating is not None and total_review == 0

    flags: list[str] = []
    if not has_rating:
        flags.append("no_rating")
    if not has_review_count:
        flags.append("missing_review_count")
    if low_review:
        flags.append("low_review")
    if not has_address:
        flags.append("missing_address")
    if rating_with_zero_reviews:
        flags.append("rating_with_zero_reviews")
    if not has_reviews:
        flags.append("no_reviews")
    if not has_hours:
        flags.append("no_hours")

    return {
        "source_url": raw.get("source_url"),
        "ta_location_id": extract_location_id(raw.get("source_url")),
        "restaurant_name": name,
        "rating": rating,
        "total_review": total_review,
        "address": address,
        "street": parts["street"],
        "house_number": parts["house_number"],
        "postal_code": parts["postal_code"],
        "city": parts["city"],
        "photo_count": parse_photo_count(raw.get("number_photo_uploaded")),
        "price_band": price_band,
        "price_tier_level": price_tier_level,
        "cuisines": cuisines,
        "opening_hours": opening_hours,
        "reviews": reviews,
        "sample_size": len(reviews),
        "website": website,
        "phone": phone,
        "email": email,
        "has_rating": has_rating,
        "has_review_count": has_review_count,
        "low_review": low_review,
        "has_address": has_address,
        "has_reviews": has_reviews,
        "has_hours": has_hours,
        "has_phone": has_phone,
        "has_website": has_website,
        "has_email": has_email,
        "flags": flags,
    }
