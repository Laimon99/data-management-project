# Google Places Seed — Strict EDA & Quality Report

> Exploratory data analysis and data-quality assessment of the Stage-1 seed
> (`data/raw/google_places/restaurants_seed.jsonl`, **N = 10,808** records),
> run to decide whether the Google source needs a **Transform (T) layer** analogous
> to the Tripadvisor `tripadvisor_clean` transform (PR #9).
>
> **Verdict: yes — but a *different kind* of transform.** Tripadvisor needed
> *repair* (decimal-comma ratings, `"(N recensioni)"` strings, pervasive `"NaN"`,
> missing coordinates → geocoding). Google data arrives **already typed, valid, and
> geocoded**, so it needs **projection + normalization + relevance flagging**, not
> repair or geocoding. See [`specs/google-places-elt-transform.md`](../../../specs/google-places-elt-transform.md).

Reproduce: the figures below come from a single deterministic pass over the JSONL
file (no sampling). All percentages are of the full 10,808 records.

---

## 1. Completeness

Core identity/geo fields are **pristine**; only the ratings pair and a few detail
fields are sparse (by nature, not by defect).

| Field | Null | Coverage |
|---|---|---|
| `place_id`, `name`, `formatted_address`, `city`, `latitude`, `longitude`, `types`, `details_fetched_at`, `seed_collected_at` | 0 | **100%** |
| `primary_type` | 24 | 99.78% |
| `rating` | 701 | 93.51% |
| `user_rating_count` | 701 | 93.51% |
| `details.priceLevel` | — | 44.65% |
| `details.priceRange` | — | 73.76% |
| `details.websiteUri` | — | 53.23% |
| `details.nationalPhoneNumber` | — | 83.52% |
| `details.regularOpeningHours` | — | 87.22% |
| `details.editorialSummary` | — | 9.88% |

`rating` and `user_rating_count` are **perfectly co-null** (rating null ⟺ count
null — 0 half-populated rows). The 701 nulls are venues with no Google reviews.

---

## 2. Validity — essentially defect-free (the key contrast with Tripadvisor)

| Check | Result |
|---|---|
| `rating` is a float in `[1.0, 5.0]` | **100%** (0 out-of-range, 0 wrong-type) |
| `user_rating_count` is an int `≥ 1` | **100%** (0 zero, 0 negative, 0 wrong-type) |
| `businessStatus` from valid enum | 100% (`OPERATIONAL` 96.2%, `CLOSED_TEMPORARILY` 3.6%, `CLOSED_PERMANENTLY` 1) |
| `priceLevel` from valid enum | 100% |
| coordinates inside Milan metro bbox | **100%** (0 outliers) |
| address contains 5-digit CAP | 99.98% (only 2 without) |
| `seed_collected_at` parseable ISO-8601 | 100% |

There is **nothing to type-coerce and nothing to geocode** — coordinates are
authoritative and never recomputed (per project architecture). Rating granularity
spans `.0`–`.9` evenly, i.e. genuine averages, not a rounding artifact.

---

## 3. Consistency

Top-level fields are near-perfectly redundant with `details`:

| Check | Result |
|---|---|
| `name` == `details.displayName.text` | 10,808 / 10,808 |
| top coords == `details.location` | 10,808 / 10,808 (0 mismatch) |
| `primary_type` ∈ `types[]` | 100% |
| top `rating` == `details.rating` | mismatch in **1** record |
| top `user_rating_count` == `details.userRatingCount` | mismatch in **119** records |

The 119 count mismatches are **temporal drift**: 115/119 have `details` slightly
*lower* than top-level (median diff = 1, max = 11) — the top-level value was captured
at seed time and the detail value at detail-fetch time. The transform must pick **one
canonical field**: `details.*`, since the detail fetch runs *after* the seed capture
and is therefore fresher.

**`city` is NOT "always Milan"** (the dataset-schema.md doc is inaccurate here), and
the field is more broadly **unreliable**:

- **62 distinct `city` values** — the seed covers the whole Milan **metropolitan
  area**: `Milano` 8960, `Sesto San Giovanni` 311, `Corsico` 129, `San Donato
  Milanese` 112, `Rozzano` 112, `Segrate` 111, `Buccinasco` 94, `Cesano Boscone` 79…
- **Spelling inconsistency for the same city**: `"Milano"` (8960) vs `"Milan"` (109) —
  the *only* EN/IT twin in the data (canonical = Italian, `Milano`).
- **Out-of-area values despite in-bbox coordinates** — even though 100% of coordinates
  are inside the Milan bbox (§2), the `city` string sometimes names a place far away:
  `Torino`, `Bergamo`, `Sasso Marconi` (near Bologna), `Vairano Patenora` (Caserta),
  `MARTINA FRANCA` (Puglia). Plus casing junk (`paperino`) and non-city labels
  (`Area Industriale`, `Stazione`, `Centro commerciale Emilia`).

→ Derive the canonical `city` from the **structured** `addressComponents.locality`
(reliable) rather than the flat string, casing-normalize it, canonicalize `Milan`→`Milano`,
and **flag** out-of-area values (`city_out_of_area`).

---

## 4. Uniqueness

| Key | Outcome |
|---|---|
| `place_id` (natural PK) | 10,808 distinct, **0 duplicates** — perfect PK |
| normalized `name` | 308 names repeat, covering 9.69% of rows — but these are **chains** (La Piadineria ×54, McDonald's ×31, Alice Pizza ×27, Esselunga ×19), **not duplicates** |
| exact coordinate | 358 clusters, 787 rows, max cluster = 10 — malls / food courts / shared buildings |
| (`name`, `address`) exact | 4 keys / 20 rows — and these are **junk placeholders** (see §6), not real dup restaurants |
| (`name`, coord ≈ 5 dp) | **0** — no genuine duplicate venues |

**The seed is effectively duplicate-free at the venue level.** `name` alone and
coordinate alone are *not* safe dedup keys (chains and shared buildings).

---

## 5. Relevance / scope — filter out the non-dining noise

The project compares **dining** ratings. Bars, cafes, bakeries and gelaterie **are in
scope** (per project decision) — the actual problem is a tail of clearly **non-dining**
venues. Classifying `primary_type` (175 distinct values) into dining tiers:

| Tier | Count | Share | In scope? |
|---|---|---|---|
| `RESTAURANT` (`*_restaurant`, bistro, food_court, steak_house, …) | 5,808 | 53.7% | ✅ |
| `CAFE_BAR_BAKERY` (bar, cafe, bakery, pub, wine_bar, gelato, …) | 4,609 | 42.6% | ✅ |
| **`NON_DINING`** (gas station, supermarket, hotel, store, spa, …) | **345** | **3.2%** | ❌ noise |
| `NULL_TYPE` / ambiguous / unclassified | 46 | 0.4% | ❌ unknown |

→ **In scope = `RESTAURANT` + `CAFE_BAR_BAKERY` = 96.4%.** Only the 3.2% hard
`NON_DINING` tier is the dilution problem.

> **Method note.** This table classifies on `primary_type` **alone** (hence the 46
> null/ambiguous "unclassified"). The transform's `classify_tier` additionally uses a
> `types[]` fallback, which rescues every null/ambiguous-`primary_type` record into a
> dining tier via its type tags — so the *transform's* output has **`tier_unknown` ≈ 0**
> and slightly higher restaurant/cafe counts (≈5,838 / 4,624 / 346 pre-drop). The 96.4%
> in-scope conclusion is unchanged.

**335 of the 345 non-dining venues carry a real Google rating**, so without filtering
they *will* pollute the unified ratings table and create false matches in entity
resolution. Concrete examples:

```
Q8                         gas_station     3.9  (229 reviews)
Esselunga                  supermarket     4.0  (4890 reviews)
Fabbrica del Vapore        cultural_center 4.3  (15081 reviews)
Hotel Manzoni              hotel           4.7  (379 reviews)
MOBA Barber                barber_shop     5.0  (126 reviews)
Bagni Misteriosi           swimming_pool   4.1  (4182 reviews)
Tamoil / Q8                gas_station     3.8 / 4.1
Centro Mood                shopping_mall   4.0  (389 reviews)
```

CLAUDE.md already anticipates this ("LLMs may be used to filter out misclassified or
noisy venues"). The transform classifies every record into `category_tier` and sets
`is_dining = restaurant OR cafe_bar_bakery`; the hard `non_dining` tier is flagged (and
optionally dropped via `--drop-non-dining`).

---

## 6. Junk / garbage records

- **~26 records whose `name` is a geographic string** rather than a venue name —
  `"Metropolitan City of Milan"` (×17), `"Milano"`, `"Novate milanese"`. Most are
  `food_court` placeholders with **no rating**; a few are rated restaurants mis-named
  with the city.
- **`food_court`: 33 records, 21 with no rating** — a disproportionately junky
  category (unnamed placeholders).
- **Non-OPERATIONAL venues: 391** (390 `CLOSED_TEMPORARILY` + **1 `CLOSED_PERMANENTLY`**),
  plus **19 with a missing `businessStatus`**. Of the 391 closed, **337 still carry a
  rating**. For a *current* ratings comparison, permanently-closed should likely be
  dropped/flagged. (The transform's `not_operational` counter = the 391 status-present
  closed records among those kept; the stored `is_operational=False` additionally
  includes the missing-status records.)

---

## 7. Field-level normalization signals on `name`

| Signal | Count | Note |
|---|---|---|
| ALL-CAPS names (`"IN PIAZZA"`) | 471 (4.36%) | casing inconsistency for display/matching |
| non-ASCII characters | 1,394 (12.9%) | **legitimate** accented Italian / CJK — informational, *not* a defect; relevant only if downstream matching wants ASCII folding |
| leading/trailing whitespace | 0 | already clean |
| internal multi-space | 0 | already clean |
| single-character names | 4 | suspicious |
| purely-numeric names | 4 | suspicious |

---

## 8. Structured address is free

The `details.addressComponents` **array** is present in **100%** of records. Unlike
Tripadvisor — where we regex-parsed a free-text string — Google hands us the address
**already decomposed** into `street_number`, `route`, `postal_code`, `locality`,
`administrative_area`, `country`. Structured extraction is a lookup, not fragile parsing.

Caveat: individual *components* are not all 100%. The `locality` component specifically
is present in **97.2%** (null in 306 records), so the transform derives `city` from
`addressComponents.locality` **and falls back to the flat `city` field** when absent.
(The flat `city` field still needs the EN/IT alias + casing fix; see §3.)

---

## 9. Timeliness

All records were collected in a **single snapshot**: `seed_collected_at` and
`details_fetched_at` both span **2026-05-24 → 2026-05-25** (0-day span). Timeliness is
uniform — no staleness *within* the seed. (The 119 count drifts in §3 are the
seed-capture vs detail-fetch gap inside that window.)

---

## 10. Payload shape

`details` accounts for **~98% of all bytes** (~24 KB per record vs ~0.5 KB for the
flat fields). A lean projection of the ~15 relevant fields keeps only **5.8% of the
bytes — i.e. ~94% is dropped**. Where that weight sits:

| `details` field | % of record bytes | needed? |
|---|---|---|
| `photos` (≤10 photo-metadata objects) | 35.5% | no |
| `reviews` (≤5 full review texts) | 24.9% | only for the *optional* LLM text extension |
| `addressDescriptor` | 8.3% | no |
| `currentOpeningHours` + `regularOpeningHours` | 10.6% | no |
| `googleMapsLinks`, `viewport`, `adrFormatAddress`, … | the rest | no |

The transform **projects** the relevant fields into a lean clean document, keeps a
**slimmed** `reviews` (≤5 × `{rating, text, language, publish_time, author}`) and a
derived `photo_count`, and leaves the 24 KB blob (full photos + reviews) in the
immutable raw collection as the audit trail / LLM-extension source.

---

## Conclusion → transform requirements

A transform **is** warranted, but it is *projection + normalization + relevance
flagging*, **not** the type-repair-and-geocode work Tripadvisor needed:

1. **Project** the relevant fields out of the 24 KB blob → lean
   `restaurants_clean_google` (raw stays as audit trail).
2. **Normalize** `city` (Milano/Milan + metro municipalities) and `name` casing; lift
   structured address from `addressComponents` (free).
3. **Flag (not delete)** non-dining venues, geographic-name junk, and closed venues,
   each with a reason — count-only, mirroring Tripadvisor's low-review decision.
4. **Canonicalize** `rating` / `review_count` (pick top-level), add `has_rating` /
   `low_review` flags.
5. Emit a before/after **`CleanReport`** that feeds the stage-5 quality deliverable.

Explicitly **out**: geocoding (coords authoritative) and type-coercion (already typed).

Full design: [`specs/google-places-elt-transform.md`](../../../specs/google-places-elt-transform.md).
