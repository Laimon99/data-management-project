"""Read-only SQL builders for the research-question analyses.

The SQL itself lives in sibling ``*.sql`` files in this package; this module is
a thin loader that reads a file and fills templated placeholders. Keeping the
SQL on disk makes the queries easy to read, diff and reuse outside Python, while
the builder functions preserve a stable Python API (``queries.q1_summary()``)
for the notebook and tests.

Templating
----------
Every ``.sql`` file may reference ``{INTEGRATED}`` (the table name),
``{min_platforms}`` (the multi-platform threshold) and ``{sparse}`` (the sparse
review-count threshold); these are injected from :mod:`analysis.constants` so the
thresholds stay single-sourced. Query-specific placeholders (e.g. ``{top_n}``)
are supplied by the corresponding builder function.

Design notes
------------
- Cross-platform "consistency" only exists for venues rated on >= 2 platforms;
  those queries carry ``rating_platform_count >= {min_platforms}``.
- Every integrated restaurant has Google (the seed), so the meaningful platform
  *pairs* are Google-Tripadvisor, Google-TheFork and (within the all-three set)
  Tripadvisor-TheFork. Consistency is reported **pairwise**, not as one blob.
- ``thefork_rating_5`` (normalized 0-5) is always used, never the raw 0-10 scale.
- Per-platform completeness uses review/photo/contact coverage — **not**
  coordinates, which were enriched downstream for Tripadvisor.
"""

from __future__ import annotations

from pathlib import Path

from ..constants import MIN_PLATFORMS_FOR_DISAGREEMENT, SPARSE_REVIEW_THRESHOLD

_SQL_DIR = Path(__file__).parent

INTEGRATED = "restaurants_integrated"

RATING_COLS = {
    "google": "google_rating_5",
    "tripadvisor": "tripadvisor_rating_5",
    "thefork": "thefork_rating_5",
}
REVIEW_COLS = {
    "google": "google_review_count",
    "tripadvisor": "tripadvisor_review_count",
    "thefork": "thefork_review_count",
}
PHOTO_COLS = {
    "google": "google_photo_count",
    "tripadvisor": "tripadvisor_photo_count",
    "thefork": "thefork_photo_count",
}
PAIRS = [
    ("google", "tripadvisor"),
    ("google", "thefork"),
    ("tripadvisor", "thefork"),
]

_DEFAULTS = {
    "INTEGRATED": INTEGRATED,
    "min_platforms": MIN_PLATFORMS_FOR_DISAGREEMENT,
    "sparse": SPARSE_REVIEW_THRESHOLD,
}


def load_sql(name: str, **params: object) -> str:
    """Read ``<name>.sql`` and fill its placeholders (defaults + ``params``)."""
    text = (_SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")
    return text.format(**{**_DEFAULTS, **params})


# --- Q0 -------------------------------------------------------------------
def q0_platform_coverage() -> str:
    return load_sql("q0_platform_coverage")


# --- Q1 — consistency -----------------------------------------------------
def q1_summary() -> str:
    return load_sql("q1_summary")


def q1_histogram() -> str:
    return load_sql("q1_histogram")


def q1_tolerance_bands() -> str:
    return load_sql("q1_tolerance_bands")


def q1_pairwise_agreement() -> str:
    return load_sql("q1_pairwise_agreement")


# --- Q2 — highest disagreement (pairwise) ---------------------------------
def q2_top_pair(a: str, b: str, *, top_n: int = 20, min_diff: float = 1.0) -> str:
    return load_sql(
        "q2_top_pair",
        a=a,
        b=b,
        rating_a=RATING_COLS[a],
        rating_b=RATING_COLS[b],
        review_a=REVIEW_COLS[a],
        review_b=REVIEW_COLS[b],
        top_n=top_n,
        min_diff=min_diff,
    )


def q2_top_all_three(top_n: int = 20) -> str:
    return load_sql("q2_top_all_three", top_n=top_n)


# --- Q3 — inconsistency vs data quality -----------------------------------
def q3_correlations() -> str:
    return load_sql("q3_correlations")


def q3_binned() -> str:
    return load_sql("q3_binned")


def q3_scatter_rows() -> str:
    return load_sql("q3_scatter_rows")


# --- Q4 — sparse inflation -------------------------------------------------
def q4_sparse_summary() -> str:
    return load_sql("q4_sparse_summary")


def q4_rating_rows() -> str:
    return load_sql("q4_rating_rows")


def q4_rating_volume_rows() -> str:
    """Row-level rating + review count per platform (Q4 volatility tiers)."""
    return load_sql("q4_rating_volume_rows")


# --- Q5 — platform bias ----------------------------------------------------
def q5_platform_rows() -> str:
    return load_sql("q5_platform_rows")


def q5_pairwise_differences() -> str:
    return load_sql("q5_pairwise_differences")


# --- Q6 — popularity vs inconsistency -------------------------------------
def q6_popularity_bins() -> str:
    return load_sql("q6_popularity_bins")


# --- Q7 — geography vs completeness ---------------------------------------
def q7_rows() -> str:
    return load_sql("q7_rows")


def q7_postal_completeness(min_restaurants: int = 30) -> str:
    return load_sql("q7_postal_completeness", min_restaurants=min_restaurants)


# --- Q8 — cuisine (extended) ----------------------------------------------
def q8_cuisine(top_n: int = 15, min_restaurants: int = 30) -> str:
    return load_sql("q8_cuisine", top_n=top_n, min_restaurants=min_restaurants)


# --- Q9 — price (extended) -------------------------------------------------
def q9_price_tier() -> str:
    return load_sql("q9_price_tier")


# --- Q10 — selection effect (extended) ------------------------------------
def q10_rating_by_coverage() -> str:
    return load_sql("q10_rating_by_coverage")


def q10_rating_by_presence() -> str:
    return load_sql("q10_rating_by_presence")


# --- Q11 — photos (extended) ----------------------------------------------
def q11_photo_correlations() -> str:
    return load_sql("q11_photo_correlations")


def q11_photo_rows(platform: str = "google") -> str:
    return load_sql(
        "q11_photo_rows",
        photo=PHOTO_COLS[platform],
        review=REVIEW_COLS[platform],
        rating=RATING_COLS[platform],
    )
