# Tripadvisor Milan — Strict EDA & Data-Quality Assessment

> Deep exploratory data analysis of the Tripadvisor extract
> (`data/raw/tripadvisor/tripadvisor_scraper_results.json`, **N = 7,539** records),
> written from a **data-analyst + data-engineer** standpoint to decide which Transform (T)
> operations genuinely improve data quality — the same lens applied to
> `google_clean` (`../google_places_api/eda-report.md`) and `thefork_clean`
> (`../thefork_scraper/eda-report.md`).
>
> **Scope: this dataset on its own merits** — type-repair, structuring, feature
> engineering, geocoding, and quality flags. Cross-source entity resolution / unified
> dataset / rating-scale harmonisation are later stages and **out of scope** here.
>
> **Verdict — a transform IS warranted, and it is the *type-repair + structuring +
> geocoding* kind.** Unlike TheFork (already typed, already geocoded) Tripadvisor ships
> **everything as page-rendered Italian display strings** (`"5,0"`, `"(1.234
> recensioni)"`, `"NaN"` sentinels) and carries **no coordinates**, so the transform must
> (a) type-repair, (b) geocode the cleaned address, (c) resolve the dataset's
> First-Normal-Form violations (price/cuisine/hours/reviews shipped as strings), and
> (d) flag quality count-only — never delete.

**Method.** Every figure below is from a single deterministic full pass over the file
(no sampling), reproduced by running the `transform.tripadvisor_clean.cleaners` parsers
over all 7,539 records; percentages are of all records unless noted.

---

## A. Shape, keys & referential integrity

13 flat fields per record; nested `review[]` (objects, or the literal string `"NaN"`).
Two interchangeable identifiers, both **7,539-distinct, 0 duplicates**:

| Candidate key | Example | Note |
|---|---|---|
| `source_url` | `…-d28119476-Reviews-Dop20-Milan_Lombardy.html` | full review URL; natural PK (→ `_id`) |
| `ta_location_id` (the `-d<n>-` token) | `28119476` | stable venue id; survives slug/locale changes |

**Referential integrity is sound:** every `source_url` yields a `ta_location_id`
(7,539/7,539). `ta_location_id` is Tripadvisor's analogue of TheFork's `tf_id` and Google's
`place_id`, and is lifted as a first-class join/blocking field for entity resolution while
`_id` stays `source_url`.

---

## B. Completeness — systematic, field-dependent missingness

| Field | Non-empty | Note |
|---|---|---|
| `source_url`, `total_review` | 100% | `total_review` is always rendered (incl. `"(0 recensioni)"`) |
| `rating` | 99.8% | 15 venues with no rating yet |
| `address` | 99.1% | 66 (0.9%) `"NaN"` — Tripadvisor showed no address |
| `phone_number` | 90.1% | |
| `review` (≥1 object) | 88.6% | 856 are `"NaN"` (zero reviews / scrape gap) |
| `website` | 79.9% | own site or social link |
| `number_photo_uploaded` | 78.9% | |
| `cuisine_type` | 77.7% | |
| `working_days_hours` | 67.6% | genuine absence, not a parse failure (see §G) |
| `price_range` | 67.7% | |
| `email` | 46.9% | most venues publish no email on Tripadvisor |

Missingness is **field-systematic** (some fields are simply not shown on many pages), not
row-systematic — there is no "dead row" class. → **Flag presence per field; never impute.**

---

## C. Validity & type system — everything is a display string (the core type-repair job)

The opposite of TheFork: **no field arrives in its correct Python type.** All values are
Italian-locale page text and must be repaired:

| Field | Raw form | Repair |
|---|---|---|
| `rating` | `"5,0"` (comma decimal) | `,`→`.`, parse float, validate `[0,5]` |
| `total_review` | `"(1.234 recensioni)"` | extract int, drop Italian thousands `.` |
| `number_photo_uploaded` | `"380"` / `"1.234"` | parse int, drop thousands `.` |
| *(all fields)* | `"NaN"` sentinel | coerce to real `null` |

Validity after repair: `rating` ∈ [1.0, 5.0] (no out-of-range), `total_review` ≥ 0,
`number_photo_uploaded` ≥ 0. The `"NaN"` string is the universal missing-value sentinel and
appears in every optional field.

---

## D. Distributions & outliers

- **`rating` — genuinely discriminative (unlike TheFork's 0–10 ceiling).** present 99.8%;
  mean **3.91**, median **4.0**, full range **1.0–5.0**. Half-step histogram: 1.0×102,
  1.5×30, 2.0×144, 2.5×244, 3.0×706, 3.5×1357, **4.0×2288**, 4.5×1778, 5.0×875. A broad,
  near-bell shape centred on 4.0 — Tripadvisor ratings carry real spread, so a
  rating-difference analysis against TheFork/Google has signal.
- **`total_review` — heavy right skew (≈ log-normal).** median **24**, mean **174**,
  max **17,673**; p90 ≈ 522, p99 ≈ 1,880. **813 venues (10.8%) have 0 reviews** — a key
  caveat: a high `rating` on 0 reviews is not comparable to one on thousands (flagged
  `rating_with_zero_reviews`).
- **`price_range` — only 4 values:** `€€-€€€` (3,071), `€` (1,657), `€€€€` (373), `NaN`
  (2,438). A clean ordinal (no `€€`/`€€€` alone ever appear).
- **`number_photo_uploaded`** — present 78.9%; integer count, right-skewed.

---

## E. Consistency & cross-field integrity

- **`rating` present with 0 reviews:** 798 records (10.6%) — a rating shown over an empty
  review base. Flag `rating_with_zero_reviews`; do not drop.
- **`rating` missing while `total_review` present:** 15 records. Do **not** backfill from
  the nested-review sample (biased, recent, ≤15 items) — flag `no_rating`.
- **Nested `review[]` is a small recent first-page sample, not the population.** Capped at
  **≤15** per record (observed max = 15) while `total_review` reaches 17,673 — so the slim
  `reviews` array is a `sample_size`, never a stand-in for `total_review`.
- **Temporal range** of nested-review dates: **2009-11-18 → 2026-06-04** (heavily recent).
  All 75,296 dates parse to ISO (§G). The scraper stamps no per-record `scraped_at`, so
  no within-record leakage check is possible — recorded as a provenance gap.

---

## F. Uniqueness — duplicate-free (verified)

| Check | Result |
|---|---|
| `source_url` | 7,539 distinct, 0 exact dups |
| `ta_location_id` | 7,539 distinct, 0 dups |
| `restaurant_name` | 7,215 distinct → **324 name collisions = chains** (McDonald's, La Piadineria, …) |

→ **No deduplication is required at the source level.** Name-alone is an unsafe identity
key (chains); `source_url`/`ta_location_id` is the safe identity.

---

## G. Structure — First-Normal-Form violations (the structuring target)

Four fields hold a *serialized structure or multi-value* inside a single string:

| Field | Raw form | Defect | Parse outcome |
|---|---|---|---|
| `price_range` | `"€€-€€€"` | glyph band | → `price_band` + ordinal `price_tier_level` (€-count of the lower bound: €→1, €€-€€€→2, €€€€→4). 5,101 parsed. |
| `cuisine_type` | `"Italiana, Pizza"` | comma-CSV multi-value | → `cuisines: list[str]`; **56 distinct tokens, clean vocab** (Italiana 4,044, Pizza 1,285, Pesce 793, …); 3,730 rows multi-cuisine. |
| `working_days_hours` | `"Domenica: Chiuso and Lunedì and 12.00-15.00 and 19.00-23.00 and Martedì and …"` | flattened weekly table; `" and "` separates **both** days and shifts; only the first day has `":"`; `Chiuso` = closed; dot-times; `12.00-1.00` past-midnight | → `opening_hours: [{day, opens, closes[, closes_next_day]}]`, English day names, split shifts preserved. **5,096/5,096 present values parse (100%)**, 0 malformed. |
| `review` | `[{author:{nickname,number_of_contribution}, title, text, date_of_publication}]` | objects with Italian dates + display artifact | → slim `reviews` (capped 20) `{nickname, contributions, title, text, date}`; **all 75,296 dates parse to ISO**; date range 2009–2026. |

---

## H. Field hygiene — display artifacts & contacts

- **Read-more artifact is universal:** **all 75,296 review texts** end with the page
  expander label `"Scopri di più"` glued to the body (`"…non cercate altro in zonaScopri
  di più"`). It is stripped during review slimming without truncating real text.
- **Contacts are real and worth keeping** (unlike TheFork's dead phone/email): `phone_number`
  90.1%, `website` 79.9% (own site or social link), `email` 46.9%. Normalised (`"NaN"`/blank
  → `null`) and paired with `has_phone` / `has_website` / `has_email`.
- **`name`**: 62 ALL-CAPS, 664 legitimately non-ASCII (accented Italian / CJK), 0
  whitespace-only after trim → whitespace collapse only (ALL-CAPS recasing deferred; names
  are mixed-language).

---

## I. Geography — no coordinates (the geocoding job)

Tripadvisor ships **no latitude/longitude** — the one thing the seed (Google) and TheFork
already have. The transform geocodes the **cleaned** address via Nominatim/OpenStreetMap
(clean-first → higher hit-rate; structured street+CAP+city+country query when parts were
extracted). Address structure is favourable: `address` contains "Milano" in **99.1%**,
a 5-digit CAP is extracted in **95.9%** (`postal_code`), `street` in **99.1%**, `city` in
**95.9%**. Geocoding is resumable (already-geocoded rows skipped) and count-flagged
(`geocode_not_found` / `missing_coordinates`) — never a drop.

---

## J. Payload

Avg record ≈ **6.6 KB** (file ~49 MB). The nested `review[]` array dominates the bytes;
slimming reviews to five fields + capping the per-record list + dropping the read-more
suffix is the main projection win, while the parsed scalar/list features (price, cuisines,
hours) are small.

---

# Recommended transformations — *real, quality-improving, within-dataset*

Tiers = build order. Each flagging item is **count-only (never deletes)**, mirroring
`thefork_clean` / `google_clean`.

### P0 — type-repair + geocoding (without these the data is unusable)
1. **`rating` `"5,0"` → float**, **`total_review` `"(1.234 recensioni)"` → int**,
   **`"NaN"` → `null`** across all fields.
2. **Geocode the cleaned address** → `latitude`/`longitude` (resumable; `--skip-geocode`
   for a fast clean-only pass).

### P1 — resolve the 1NF violations (structuring)
3. **`price_range` → `price_band` + ordinal `price_tier_level`.**
4. **`cuisine_type` CSV → `cuisines: list[str]`** (trim, de-dupe case-insensitively).
5. **`working_days_hours` flattened string → `opening_hours` array** (the conservative,
   automatic Italian-string parser; 100% of present values parse).
6. **`number_photo_uploaded` → `photo_count` (int).**
7. **`review` → slim, capped `reviews`** `{nickname, contributions, title, text, date}`;
   strip the universal `"Scopri di più"` suffix; parse Italian dates to ISO.

### P2 — schema hygiene & honest quality flags (count-only, never delete)
8. **Lift `ta_location_id`** (the `-d<n>-` token) as a first-class id/blocking field;
   `_id` stays `source_url`.
9. **Normalize contacts** (`website`/`phone_number`/`email`: `"NaN"`/blank → `null`) +
   `has_phone` / `has_website` / `has_email`.
10. **Structured address parts** (`street` / `postal_code` / `city`) on top of the
    normalized full `address` (the source of truth).
11. **Quality flags:** `has_rating`, `has_review_count`, `low_review` (count-only),
    `has_address`, `has_coordinates`, `has_reviews`, `has_hours`,
    `rating_with_zero_reviews`, plus the geocode flags. Drop the replaced raw fields from
    the clean doc (the raw collection stays the audit trail).

### Explicit NON-goals (justified by this EDA — don't do these)
- ❌ **Deduplication** — verified duplicate-free; name collisions are real chains.
- ❌ **Backfilling null ratings from the review sample** — biased, recent, ≤15 items.
- ❌ **Relevance/non-dining filtering** — the URL list is curated Milan restaurants.
- ❌ **Default record drops** — flag-first; see `../../transform/tripadvisor_clean/drop-policy.md`.
- ❌ **Cross-source rating-scale harmonisation, translation, cuisine-vocab mapping** —
  integration/analysis stages, not this transform.

A before/after **`CleanReport`** (parsed-field coverage, flags raised, raw fields dropped,
`stale_deleted`) accompanies every run, feeding the stage-5 quality deliverable — exactly
as `thefork_clean` and `google_clean` do.
