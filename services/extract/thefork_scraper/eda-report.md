# TheFork Milan — Strict EDA & Data-Quality Assessment

> ⚠️ **This analysis is of the *pre*-2026-06-06 scrape.** A newer scrape has since landed
> (reviews tripled, coordinates complete, `working_hours_structured` added, `website`/
> dietary/multi-cuisine lost) — see [`../../../docs/the_fork_migration/DATASET_CHANGES.md`](../../../docs/the_fork_migration/DATASET_CHANGES.md)
> for the deltas and [`../../../specs/thefork-elt-transform.md`](../../../specs/thefork-elt-transform.md)
> for how the transform reflects the new version. The findings below remain the
> methodological record; specific counts are from the older file.

> Deep exploratory data analysis of the TheFork extract
> (`data/raw/thefork/thefork_milan_restaurants_enriched.json`, **N = 1,344** records),
> written from a **data-analyst + data-engineer** standpoint to decide whether the source
> needs a Transform (T) layer like `tripadvisor_clean` (PR #9) / `google_clean` (PR #10),
> and *which* transformations genuinely improve data quality.
>
> **Scope: this dataset on its own merits** — cleaning, structuring, feature engineering,
> and quality flags. Cross-source entity resolution / unified dataset / rating-scale
> harmonisation are later stages and **out of scope** here.
>
> **Verdict — a transform IS warranted, and it is the *structuring/parsing* kind.**
> TheFork is **already typed and already geocoded** (no numeric type-repair, no
> geocoding — the two things Tripadvisor needed), is **duplicate-free** (no dedup), and
> is **all dining** (no relevance filtering). What it carries instead is **First-Normal-
> Form violations**: several of its richest fields are *serialized structures or
> multi-value strings* the scraper left as raw display text. The transform's real job is
> **parse → structure → flag**, plus dead-field hygiene.

**Method.** Every figure below is from a single deterministic full pass over the file
(no sampling); percentages are of all 1,344 records. Cross-checks (co-null cross-tabs,
sample-vs-platform rating divergence, fuzzy near-duplicate detection, slug↔name
integrity, temporal leakage, missingness-vs-scrape-depth) were computed explicitly.

**Housekeeping.** `…_enriched.json` and `…_normalized_partial.json` are **byte-for-byte
identical**; consume `…_enriched.json` only. Note `enriched` ≠ "cleaned" — per the
scraper spec, "normalized/aligned with Google & Tripadvisor" means a **shared field
envelope (same column names + JSON shape)**, *not* clean or comparable values. That
naming is exactly what makes the source look done when it is not.

---

## A. Shape, keys & referential integrity

23 flat fields per record; nested `reviews[]` (objects) and `review_snippets[]`
(strings). Three interchangeable identifiers, all **1,344-distinct, 0 duplicates**:

| Candidate key | Example | Note |
|---|---|---|
| `source_id` | `drinkiamo-bistrot-r801007` | slug + `-r<id>`; natural PK |
| `restaurant_url` | `…/ristorante/drinkiamo-bistrot-r801007` | 1:1 with `source_id` |
| `tf_id` (the `-r<n>` token) | `801007` | stable venue id; survives slug changes |

**Referential integrity is perfect:** `restaurant_name` slugifies to the `source_id`
slug in **1,344/1,344** records (0 mismatches) — `source_id` is trustworthy and
name-derived. `tf_id` is the analogue of Tripadvisor's `ta_location_id` and should be
lifted as a first-class join/blocking field.

---

## B. Completeness — and the missingness is **systematic (MAR), not random**

| Field | Non-empty | Note |
|---|---|---|
| `source`,`source_id`,`restaurant_name`,`address`,`city`,`restaurant_url`,`price_range`,`scraped_at`,`source_page_number`,`detail_scraped` | 100% | |
| `latitude`/`longitude` | 99.8% | 3 missing = the 3 un-scraped rows |
| `review_count` | 97.0% | 40 null |
| `rating` | 96.7% | 44 null |
| `photo_count` | 99.7% | |
| `cuisine_type` | 99.0% | 14 null |
| `discount` | 70.6% | 395 null = legitimately "no promo" |
| `working_days_hours` | 63.5% | 491 null — genuinely absent, *not* a scrape failure (see §E) |
| `review_snippets` / `reviews` | 96.1% / 95.2% | 53 / 64 empty lists |
| **`website`** | **1.9%** | and mislabeled (§H) |
| **`phone_number`** / **`email`** | **0% / 0%** | dead fields (§H) |

**The 44 missing ratings are a scrape-depth artifact, not a property of the venues:**

- rating-null rate climbs monotonically with listing-page depth — **p1–18: 1/452 ·
  p19–36: 10/448 · p37–54: 33/444**.
- rating-null is **2%** when `review_count` is present but **42%** when `review_count`
  is also null — the two co-fail together (joint detail-capture gap).

→ **Treat "no rating" as "not captured", not "unrated."** Flag it; never impute it
(see §E for why nested reviews cannot backfill it). `rating` and `review_count` are
**best-effort scraped values, not authoritative counts** — a key caveat for any derived
metric.

---

## C. Validity & type system — already clean, with two scale facts

The flat fields arrive in their **correct Python types** — there is **nothing to
type-coerce** (the opposite of Tripadvisor's `"5,0"` / `"(N recensioni)"` strings):

| Field | Raw type | Validity |
|---|---|---|
| `rating` | `float` | numbers only, no wrong-type |
| `review_count` | `int` | `≥ 0` (4 zeros, 0 negative) |
| `latitude`/`longitude` | `float` | **100% inside Milan bbox**, 0 outliers |
| `photo_count` | `int` | 1–131 |
| `detail_scraped` | `bool` | 1,341 True / 3 False |

Two facts to record (not defects):
1. **`rating` is on a 0–10 scale** (TheFork-native): range 2.0–10.0, **99.5% > 5**. Valid;
   different *domain* from a 0–5 star, but harmonising scales is an integration concern.
2. **Coordinate precision is heterogeneous** — decimal places range 3→15 (1,035 rows at
   7 dp, 128 at 14 dp, a handful at 3–5 dp). This is a **provenance signal** (JSON-LD vs
   GraphQL vs listing extraction), not an error; the low-precision (3–4 dp ≈ 11–100 m)
   rows are slightly coarser but in-bbox. No action beyond awareness.

---

## D. Distributions & outliers

- **`rating` — pronounced ceiling effect / low discriminative power.** mean **8.85**,
  median **9.0**, std **0.66**; **50.9% ≥ 9.0**, only **1.5% < 7.0**, **7 records ≤ 5.0**.
  Half-point histogram peaks hard at 9.0 (590) and 8.5 (293). This is classic
  booking-platform rating inflation — *document it as a quality characteristic*
  (variance is tiny; a "rating difference" analysis on TheFork alone has little spread).
  The genuine low outliers (2.0×2, 3.5×2, 4.0, 4.5×2 …) are real, not errors.
- **`review_count` — heavy right skew (≈ log-normal).** median **343**, mean **847**,
  max **14,391**; p90 ≈ 2,196, p99 ≈ 6,842.
- **`price_range` (avg price €)** — median **27**, p95 **60**, p99 **110**; high tail
  150–260 € (fine dining, plausible). **One outlier `"1 €"`** = "Next Gen Lab - Temporary
  Food Court" placeholder.
- **`photo_count`** — median 16, p95 56, max 131.

---

## E. Consistency & cross-field integrity

- **Nested `reviews[]` is a tiny *recent sample*, not the population.** Capped at **≤5**
  (avg 4.67) while `review_count` reaches 14,391. `|rating − mean(nested ratings)|` has
  median 0.40 but **p95 = 1.50 and 164 records diverge by > 1.0**. → **Do NOT backfill
  the 44 null ratings from nested reviews** — it would substitute a biased 5-review
  sample for a platform average over thousands. (96% of sampled reviews are < 1 year old
  — the sample is *recent*, hence not representative of the lifetime average.)
- **`rating` / `review_count` are NOT co-null** (unlike Google's perfectly co-null pair):
  1,277 both-present, 23 rating-only, 27 count-only, 17 both-null. Mild internal
  inconsistency from listing-vs-detail capture.
- **`detail_scraped` is a clean integrity flag.** False ⟺ all 3 rows miss
  coords+hours+reviews. Among the 1,341 True rows: **0 missing coordinates** (fully
  geocoded), but 488 still miss hours and 61 miss reviews → **missing hours is genuine
  absence, not a scrape failure.** `review_count > 0` yet 0 nested reviews in 23 rows
  (detail gap).
- **Temporal integrity is sound:** **0/6,277** review dates fall after their record's
  `scraped_at` (no leakage); recency `<1y` 6,047 · `1–3y` 172 · `3–5y` 43 · `>5y` 15.
  Scrape window 2026-05-29 → 06-04.
- **`city` is a constant `"Milan"`** (EN) while every address says `"Milano"` (IT) —
  uninformative *and* inconsistent with the address. → normalise `Milan → Milano`
  (locked: same city).

---

## F. Uniqueness — effectively duplicate-free (verified, not assumed)

| Check | Result |
|---|---|
| `source_id` / `restaurant_url` / `restaurant_name` | 1,344 distinct each, 0 exact dups |
| normalized-name collisions (strip *ristorante/osteria/milano*/punct) | **1 pair**: `Fresco&Cimmino` vs `Fresco & Cimmino` |
| that pair, inspected | **two real branches ~5 km apart** (`r460035` @ Via Foscolo vs `r813038` @ Via Daimler) — **not a duplicate** |
| same ~11 m coordinate bucket | 51 buckets / 103 rows — distinct venues sharing a building/plaza (e.g. *Fishbar* / *Salotto Brera*) |

→ **No deduplication is required.** Name-alone and coordinate-alone are unsafe dedup
keys (branches, shared buildings); `source_id`/`tf_id` is the only safe identity.

---

## G. Structure — First-Normal-Form violations (the real transform target)

Five fields hold a *serialized structure or multi-value* inside a single string. These —
not types or geocoding — are TheFork's actual data-quality debt:

| Field | Raw form | Defect | Parse outcome |
|---|---|---|---|
| `working_days_hours` | `'[{"@type":"OpeningHoursSpecification","opens":"12:00","closes":"15:00","dayOfWeek":["lunedì"]}, …]'` | **a JSON document stored as text** | **all 853 parse, 0 malformed**; uniform schema `{@type,opens,closes,dayOfWeek}`, one day per spec, Italian day vocab (visible Monday-closure: *lunedì* 1037 vs *giovedì* 1357) |
| `cuisine_type` | `"Piatti vegetariani, Italiano, Europeo"` | **comma-CSV multi-value**, mixing cuisines + dietary tags | 646 rows ≥2 values; **72 distinct tokens, 0 casing/spelling variants** (clean vocab); dietary/religious tags interleaved: *Piatti vegetariani* 471, *Opzioni senza glutine* 177, *Piatti vegani* 122, *Piatti biologici* 31, *Halal* 11, *Kosher* 1; one noise token *"Solo in Italiano"* (×3) |
| `price_range` | `"30 €"` | **number+unit string** | **1,344/1,344 parse** to int €; median 27; one `"1 €"` outlier |
| `discount` | `"sconto -20%"` | **free text with embedded %**, plus review-bleed noise | clean pct always extractable `{20:474, 30:326, 50:117, 40:26, 25:5, 15:1}`; **~16 noise values** = review text leaked in (embedded `\n`, e.g. *"sconto the fork. 111 euro in due senza vino e con il 50%"*) |
| `address` | `"Via Imperia, 13, Milano, 20142, Italia"` | **composite** (street/civic/city/CAP/country in one string) | 99.8% CAP, all **20xxx** (valid Milan); but **65 use `I-20xxx`** intl prefix, **19 use EN "Milan"/"Milan, Italy"**, 5 have no civic number, abbreviations like `V.le`; 154 deviate from the canonical 4-comma shape → splittable but needs defensive parsing |

---

## H. Field hygiene — dead & mislabeled fields

- **`phone_number` — 100% null (0/1,344)** → drop.
- **`email` — 100% null (0/1,344)** → drop. (The scraper kept both despite its own spec
  rule against always-null fields, only because they belong to the shared envelope.)
- **`website` — 1.9% and mislabeled:** all 25 values are
  `guide.michelin.com/…?utm_source=thefork&utm_medium=partner` **Michelin-guide referral
  links**, never the restaurant's own site → don't expose as `website`; rename to
  `michelin_url` (+ a `has_michelin_guide` flag) or drop.
- **Nested review `title` — 100% null (0/6,277)** → drop from the slimmed review object.
- **`name`** — 26 ALL-CAPS, 0 whitespace issues, 128 legitimately non-ASCII (accented
  Italian / CJK) → light ALL-CAPS recase only.

---

## I. Text & encoding quality

Review text is **clean**: 0 mojibake/encoding artifacts across 6,277 texts (GraphQL
extraction preserved UTF-8), 0 empty, lengths 1–1,626 (no truncation pileup), 101
emoji-bearing. **`review_snippets` is largely redundant:** **68% (4,330/6,331)** of
snippets are substrings of a full `reviews[].text`. → keep one source of review text;
snippets add little beyond the 32% that have no matching full review.

---

## J. Payload

Avg record ≈ **2.8 KB** (file ~4.6 MB — small; projection is about *cleanliness*, not
size). `reviews` 39% + `working_days_hours` 28% + `review_snippets` 22% = **~89%** of
bytes; the slimmed review array + parsed hours are what to keep.

---

# Recommended transformations — *real, quality-improving, within-dataset*

Pruned to what genuinely raises quality. Tiers = build order. Each item is **count-only
where it flags** (never deletes), mirroring `tripadvisor_clean` / `google_clean`.

### P0 — resolve the 1NF violations (the core value; unlocks otherwise-unusable data)
1. **`price_range "30 €" → `avg_price_eur` (int).** 100% parseable. Numeric, queryable,
   sortable. (Keep the raw string in the audit collection.)
2. **`cuisine_type` CSV → `cuisines: list[str]` + `dietary_options: list[str]`** (lift
   *vegetariani/vegani/senza glutine/biologici/Halal/Kosher* out of the cuisine list;
   drop the *"Solo in Italiano"* noise token). Enables faceting/filtering; removes the
   multi-value-in-string defect.
3. **`working_days_hours` JSON-string → parsed `opening_hours` array** (real JSON; one
   `{day, opens, closes}` per entry, days normalised to a stable vocabulary). It is
   literally serialized JSON — `json.loads` is the minimum; a tidy per-day shape is the
   quality win.
4. **`discount` free-text → `discount_pct` (int) + `has_discount` (bool).** Extract the
   percentage **only** from clean promo patterns; route the ~16 review-bleed strings to
   `discount_pct = null` (don't trust a % scraped out of a review sentence).

### P1 — normalization & schema hygiene
5. **Drop `phone_number`, `email`** (100% null) and **demote `website`** → `michelin_url`
   + `has_michelin_guide` (it is not a website).
6. **Lift `tf_id`** (the `-r<n>` token) as a first-class stable id/blocking field; keep
   `_id` = `source_id`/`restaurant_url`.
7. **`city` `"Milan" → "Milano"`** (constant, EN→IT; locked).
8. **`name`**: collapse whitespace + best-effort ALL-CAPS recase (26 rows).
9. **`address` → normalize + structured split** (`street`, `postal_code`, `city`):
   strip the `I-` CAP prefix, fold EN `Milan→Milano`, handle the 154 non-canonical forms
   defensively (the full normalized string stays the source of truth).

### P2 — derived features & honest quality flags (count-only, never delete)
10. **Quality flags:** `has_rating`, `has_reviews`, `has_hours`, `low_review`
    (count-only, *documented as possibly scrape-incomplete*), `scrape_incomplete`
    (the 3 `detail_scraped=False` rows + the page-depth missingness caveat).
11. **Honest review-sample features** (clearly *sample*, never a stand-in for the
    platform numbers): `sample_size = len(reviews)`, `sample_avg_rating`,
    `rating_sample_divergent` (the 164 rows where |rating − sample mean| > 1).
12. **Slim `reviews`** to `{author, rating, text, date}` (drop the always-null `title`);
    keep `review_snippets` only where they are **not** already a substring of a full
    review (or drop — 68% are redundant).
13. *(Optional, clearly-labeled)* `rating_5 = rating / 2` as a 0–5 convenience view —
    leans toward integration, so optional here.

### Explicit NON-goals (justified by the EDA — don't do these)
- ❌ **Geocoding** — 99.8% present, 100% in-bbox, authoritative.
- ❌ **Numeric type-coercion of `rating`/`review_count`** — already typed.
- ❌ **Backfilling null ratings from nested reviews** — sample is recent & biased
  (p95 divergence 1.5; 164 rows >1 apart).
- ❌ **Deduplication** — verified duplicate-free (`Fresco&Cimmino` = 2 branches).
- ❌ **Relevance/non-dining filtering** — the slice is 100% Milan restaurants.
- ❌ **Cross-source rating-scale harmonisation, translation, price-tier bucketing** —
  integration/analysis stages, not this transform.

A before/after **`CleanReport`** (parsed-field coverage, flags raised, dead fields
dropped) should accompany the run, feeding the stage-5 quality deliverable — exactly as
`tripadvisor_clean` and `google_clean` do.
