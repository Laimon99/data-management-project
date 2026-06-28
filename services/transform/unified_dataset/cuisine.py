"""Canonical cuisine taxonomy + cross-platform merge for the integrated dataset.

The three sources speak three different cuisine vocabularies, and nobody reconciled
them:

* **Tripadvisor** — Italian *feminine* adjectives (``Italiana``, ``Asiatica``).
* **TheFork** — Italian *masculine* adjectives (``Italiano``, ``Asiatico``) plus many
  regional Italians (``Lombardo``, ``Toscano``…).
* **Google** — an English ``primary_type`` + ``types[]`` controlled vocabulary
  (``italian_restaurant``, ``pizza_restaurant``…), covering ~every venue but mostly
  *non-food* (``food_store``, ``night_club``, ``florist``…).

This module maps every observed raw label to a small ``canonical_cuisine_list`` and
merges the per-venue labels into a single ``primary`` bucket plus the full ``tags``
set. The map is built from the *complete* exploded inventory of all three platforms
(Tripadvisor 51 labels, TheFork 57, Google ~130 food types).

Design choices (auditable on purpose, this is a data-management deliverable):

* **Explicit map, not stemming.** Stemming can't translate Google's English and would
  mis-merge ``Pesce``/``Pizza``; a hand-map also documents the judgement calls.
* **Multi-label.** Most venues carry several cuisines, so we keep the union as ``tags``
  and additionally derive one ``primary`` for one-point-per-venue charts.
* **Specificity-ranked consensus** picks the primary: the most specific bucket wins
  (``Pizza`` beats umbrella ``Italian``; ``Chinese`` beats umbrella ``Asian``), ties
  broken by source precedence Tripadvisor > TheFork > Google.

Judgement calls encoded below: regional Italians → ``Italian``; ``tex mex``/``taco``/
``burrito`` → ``Mexican``; ``gastropub``/``brewpub``/``irish_pub`` → ``Café/Bakery/Bar``;
``fish_and_chips`` → ``British/Irish``; ``acai_shop`` → ``Hawaiian`` (poke/açaí).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

# --- canonical buckets -> the raw labels that map to them -------------------
# Keys are the canonical display names; values are raw labels (lowercased,
# stripped) from any platform. Google snake_case types and Italian-language
# Tripadvisor/TheFork labels never collide, so a single inverted map is safe.
_BUCKET_LABELS: dict[str, list[str]] = {
    "Italian": [
        "italiana",
        "italiano",
        "italiana - centro",
        # regional Italians (mostly TheFork, some Tripadvisor)
        "lombardo",
        "milanese",
        "romano",
        "siciliano",
        "toscano",
        "sardo",
        "pugliese",
        "campano",
        "campana",
        "piemontese",
        "napoletano",
        "abruzzese",
        "emiliano",
        "emiliana",
        "salentino",
        "cilentano",
        "romagnolo",
        "marchigiano",
        "umbro",
        "trentino",
        "piacentino",
        "calabrese",
        "italian_restaurant",
    ],
    "Pizza": ["pizza", "pizzeria", "pizza_restaurant", "pizza_delivery"],
    "Seafood": ["pesce", "di pesce", "seafood_restaurant", "oyster_bar_restaurant"],
    "Chinese": [
        "cinese",
        "chinese_restaurant",
        "cantonese_restaurant",
        "dim_sum_restaurant",
        "hot_pot_restaurant",
        "dumpling_restaurant",
        "chinese_noodle_restaurant",
    ],
    "Japanese": [
        "giapponese",
        "sushi",
        "japanese_restaurant",
        "sushi_restaurant",
        "ramen_restaurant",
        "japanese_izakaya_restaurant",
        "yakitori_restaurant",
        "yakiniku_restaurant",
        "japanese_curry_restaurant",
    ],
    "Korean": ["coreana", "coreano", "korean_restaurant", "korean_barbecue_restaurant"],
    "Thai": ["tailandese", "thailandese", "thai_restaurant"],
    "Vietnamese": ["vietnamita", "vietnamese_restaurant"],
    "Indonesian": ["indonesian_restaurant"],
    "Filipino": ["filippina", "filipino_restaurant"],
    "Taiwanese": ["taiwanese", "taiwanese_restaurant"],
    "Asian": [
        "asiatica",
        "asiatico",
        "orientale",
        "asian_restaurant",
        "asian_fusion_restaurant",
        "noodle_shop",
        "cambodian_restaurant",
    ],
    "Indian": [
        "indiana",
        "indiano",
        "pakistana",
        "indian_restaurant",
        "south_indian_restaurant",
        "north_indian_restaurant",
        "pakistani_restaurant",
        "sri_lankan_restaurant",
        "bangladeshi_restaurant",
    ],
    "Middle Eastern": [
        "mediorientale",
        "libanese",
        "turca",
        "araba",
        "lebanese_restaurant",
        "turkish_restaurant",
        "middle_eastern_restaurant",
        "persian_restaurant",
        "afghani_restaurant",
        "halal_restaurant",
        "kebab_shop",
        "gyro_restaurant",
        "shawarma_restaurant",
        "falafel_restaurant",
    ],
    "African": [
        "africana",
        "africano",
        "marocchina",
        "marocchino",
        "etiope",
        "eritreo",
        "african_restaurant",
        "moroccan_restaurant",
        "ethiopian_restaurant",
    ],
    "Mexican": [
        "messicana",
        "messicano",
        "tex mex",
        "mexican_restaurant",
        "tex_mex_restaurant",
        "taco_restaurant",
        "burrito_restaurant",
    ],
    "Latin American": [
        "latino americana",
        "sudamericana",
        "sudamericano",
        "caraibica",
        "cubana",
        "cubano",
        "argentina",
        "argentino",
        "brasiliano",
        "colombiano",
        "south_american_restaurant",
        "latin_american_restaurant",
        "brazilian_restaurant",
        "argentinian_restaurant",
        "colombian_restaurant",
        "caribbean_restaurant",
        "cuban_restaurant",
    ],
    "Peruvian": ["peruviana", "peruviano", "peruvian_restaurant"],
    "Mediterranean": ["mediterranea", "mediterraneo", "mediterranean_restaurant"],
    "Hawaiian": ["hawaiana", "hawaiano", "hawaiian_restaurant", "acai_shop"],
    "American": [
        "americana",
        "americano",
        "american_restaurant",
        "hamburger_restaurant",
        "hot_dog_restaurant",
        "hot_dog_stand",
        "chicken_restaurant",
        "chicken_wings_restaurant",
        "bar_and_grill",
        "diner",
        "soul_food_restaurant",
        "californian_restaurant",
        "buffet_restaurant",
        "western_restaurant",
    ],
    "Steakhouse/Grill": [
        "steakhouse",
        "barbecue",
        "di carne",
        "steak_house",
        "barbecue_restaurant",
    ],
    "Fast food": [
        "fast food",
        "street food",
        "fast_food_restaurant",
        "sandwich_shop",
        "meal_takeaway",
        "food_court",
        "snack_bar",
        "bagel_shop",
    ],
    "French": ["francese", "french_restaurant"],
    "Spanish": ["spagnola", "spagnolo", "spanish_restaurant", "tapas_restaurant"],
    "Greek": ["greca", "greco", "greek_restaurant"],
    "British/Irish": [
        "britannica",
        "irlandese",
        "british_restaurant",
        "irish_pub",
        "fish_and_chips_restaurant",
    ],
    "European": [
        "europea",
        "europeo",
        "tedesca",
        "russa",
        "russo",
        "esteuropea",
        "est europa",
        "scandinavo",
        "european_restaurant",
        "eastern_european_restaurant",
        "german_restaurant",
        "bavarian_restaurant",
        "belgian_restaurant",
        "russian_restaurant",
        "romanian_restaurant",
        "ukrainian_restaurant",
        "australian_restaurant",
    ],
    "International/Fusion": [
        "internazionale",
        "cucina internazionale",
        "cucina locale",
        "fusion",
        "gastronomia",
        "fusion_restaurant",
        "fine_dining_restaurant",
        "family_restaurant",
        "brunch_restaurant",
        "breakfast_restaurant",
    ],
    "Health/Veg": [
        "salutistica",
        "vegetarian_restaurant",
        "vegan_restaurant",
        "salad_shop",
        "juice_shop",
        "health_food_store",
    ],
    "Café/Bakery/Bar": [
        "caffetteria",
        "cafe",
        "coffee_shop",
        "bakery",
        "pastry_shop",
        "cake_shop",
        "confectionery",
        "dessert_shop",
        "dessert_restaurant",
        "ice_cream_shop",
        "chocolate_shop",
        "candy_store",
        "donut_shop",
        "tea_house",
        "tea_store",
        "coffee_roastery",
        "coffee_stand",
        "internet_cafe",
        "dog_cafe",
        "deli",
        "bar",
        "wine_bar",
        "cocktail_bar",
        "pub",
        "lounge_bar",
        "sports_bar",
        "beer_garden",
        "brewery",
        "brewpub",
        "gastropub",
        "cafeteria",
        "bistro",
        "hookah_bar",
    ],
}

OTHER = "Other"

# Inverted lookup: raw label -> canonical bucket.
RAW_TO_BUCKET: dict[str, str] = {
    raw: bucket for bucket, labels in _BUCKET_LABELS.items() for raw in labels
}

# Specificity tiers for the primary tie-break. Umbrella buckets whose more
# specific children are *also* buckets lose to those children (tier 0);
# ``Italian`` is broad but loses only to its child ``Pizza`` (tier 1);
# everything else is specific (tier 2).
GENERIC_BUCKETS = frozenset(
    {
        "Asian",
        "European",
        "Mediterranean",
        "International/Fusion",
        "Café/Bakery/Bar",
        "Health/Veg",
        "Latin American",
        OTHER,
    }
)
_BROAD_BUCKETS = frozenset({"Italian"})

# Source precedence for ties (lower = preferred).
_SOURCE_ORDER = ("tripadvisor", "thefork", "google")

# Google types that are present but carry no cuisine signal — skipped silently
# (the full non-food tail is just "anything not in RAW_TO_BUCKET").
_GOOGLE_NON_CUISINE = frozenset({"restaurant", "food", "point_of_interest", "establishment"})


def canonical_cuisine_list() -> list[str]:
    """The authoritative list of canonical cuisine buckets (sorted)."""
    return sorted(_BUCKET_LABELS)


def _key(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    key = raw.strip().lower()
    return key or None


def _specificity(bucket: str) -> int:
    if bucket in GENERIC_BUCKETS:
        return 0
    if bucket in _BROAD_BUCKETS:
        return 1
    return 2


def _dedupe(buckets: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for bucket in buckets:
        if bucket not in seen:
            seen.append(bucket)
    return seen


def normalize_labels(
    labels: Sequence[Any] | None, *, allow_other: bool
) -> tuple[list[str], list[str]]:
    """Map a list of raw labels to canonical buckets.

    Returns ``(buckets, unmapped)``. ``allow_other`` is ``True`` for the human
    cuisine vocabularies (Tripadvisor/TheFork — every label *is* a cuisine, so an
    unmapped one becomes ``Other``) and ``False`` for Google (whose ``types[]`` are
    mostly non-food, so unmapped entries are dropped, not turned into ``Other``).
    """
    buckets: list[str] = []
    unmapped: list[str] = []
    had_label = False
    for raw in labels or []:
        key = _key(raw)
        if key is None or key in _GOOGLE_NON_CUISINE:
            continue
        had_label = True
        bucket = RAW_TO_BUCKET.get(key)
        if bucket is not None:
            buckets.append(bucket)
        else:
            unmapped.append(key)
    buckets = _dedupe(buckets)
    if allow_other and had_label and not buckets:
        buckets = [OTHER]
    return buckets, unmapped


def _most_specific(buckets: Sequence[str]) -> str | None:
    """The most specific bucket in a single source's list (insertion order tie-break)."""
    best: str | None = None
    best_rank = -1
    for bucket in buckets:
        rank = _specificity(bucket)
        if rank > best_rank:
            best, best_rank = bucket, rank
    return best


def merge_cuisine(
    tripadvisor_cuisines: Sequence[Any] | None,
    thefork_cuisines: Sequence[Any] | None,
    google_classification: dict[str, Any] | None,
) -> dict[str, Any]:
    """Reconcile the three sources' cuisine labels into one record.

    Returns a dict with ``tags`` (sorted union of canonical buckets), ``primary``
    (specificity-ranked consensus), ``primary_source`` (which platform the primary
    came from), ``n_sources`` (platforms with an opinion), ``agreement``
    (``single``/``agree``/``disagree`` on the per-source primary) and ``unmapped``
    (raw labels not in the map, for logging/extension).
    """
    google_types: list[Any] = []
    if google_classification:
        primary_type = google_classification.get("primary_type")
        if primary_type is not None:
            google_types.append(primary_type)
        types = google_classification.get("types")
        if isinstance(types, list):
            google_types.extend(types)

    ta_buckets, ta_unmapped = normalize_labels(tripadvisor_cuisines, allow_other=True)
    tf_buckets, tf_unmapped = normalize_labels(thefork_cuisines, allow_other=True)
    g_buckets, g_unmapped = normalize_labels(google_types, allow_other=False)

    per_source = {"tripadvisor": ta_buckets, "thefork": tf_buckets, "google": g_buckets}

    # Union of tags (sorted for deterministic storage).
    tags = sorted({bucket for buckets in per_source.values() for bucket in buckets})

    # Primary: scan sources in precedence order for the highest-specificity bucket.
    best_rank = max((_specificity(b) for b in tags), default=-1)
    primary: str | None = None
    primary_source: str | None = None
    for source in _SOURCE_ORDER:
        for bucket in per_source[source]:
            if _specificity(bucket) == best_rank:
                primary, primary_source = bucket, source
                break
        if primary is not None:
            break

    # Agreement: compare each opining source's own primary.
    source_primaries = {
        source: _most_specific(buckets) for source, buckets in per_source.items() if buckets
    }
    n_sources = len(source_primaries)
    if n_sources <= 1:
        agreement = "single"
    elif len(set(source_primaries.values())) == 1:
        agreement = "agree"
    else:
        agreement = "disagree"

    return {
        "tags": tags,
        "primary": primary or "",
        "primary_source": primary_source or "",
        "n_sources": n_sources,
        "agreement": agreement,
        "unmapped": _dedupe([*ta_unmapped, *tf_unmapped, *g_unmapped]),
    }
