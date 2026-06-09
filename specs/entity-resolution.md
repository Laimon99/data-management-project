# Spec for entity-resolution
branch: feature/entity-resolution

## Summary

Implement a record linkage service (`services/transform/entity_resolution`) that resolves
restaurant entities across the three cleaned source collections into confirmed match pairs,
non-matches, and uncertain pairs requiring LLM resolution.

**Two independent pairings are produced:**

- `restaurants_clean_google` × `restaurants_clean_tripadvisor`
- `restaurants_clean_google` × `restaurants_clean_thefork`

Google is always the **anchor**: every candidate pair has exactly one Google record and one
source record. The Google input is pre-filtered to `is_dining=true` **and**
`is_operational=true` (10,054 records). The output is a Mongo collection
`entity_resolution_candidates` with a `label` field of `MATCH`, `NON_MATCH`, or
`UNCERTAIN`. Uncertain pairs feed a separate LLM-resolution step (out of scope here).

**Current state of the data (observed from Mongo audit):**

| Collection | Docs | Coords | PostalCode | Phone | Website |
|---|---|---|---|---|---|
| `restaurants_clean_google` (anchor) | 10,054 | 100% | 100% | 83.6% | 52.8% |
| `restaurants_clean_tripadvisor` | 7,539 | 84.1% (6,335) | 95.9% | 90.1% | 79.9% |
| `restaurants_clean_thefork` | 1,344 | 99.8% | 99.8% | n/a | n/a |

TA coordinates are from a geocoding pass already run against the collection (84.1%
populated). 1,204 TA records still lack coordinates; 101 of those also lack a postal code
and are **unblockable** with any currently available key.

---

## Data Audit Findings

Numbers observed from a live Mongo query of the three clean collections (run 2026-06-08).
These figures informed every design decision below; re-run the audit if the collections
are refreshed before implementation begins.

### Collection sizes and anchor pool

| Collection | Total docs | After `is_dining + is_operational` filter |
|---|---|---|
| `restaurants_clean_google` | 10,786 | **10,054** (anchor pool) |
| `restaurants_clean_tripadvisor` | 7,539 | — |
| `restaurants_clean_thefork` | 1,344 | — |

### Coordinate coverage

| Source | Has coordinates | Missing coords |
|---|---|---|
| Google | 10,786 / 10,786 (100%) | 0 |
| Tripadvisor | **6,335 / 7,539 (84.1%)** | 1,204 |
| TheFork | 1,341 / 1,344 (99.8%) | 3 |

Tripadvisor's geocode pass has already run; 84.1% is the current state, not 0%.
Of the 1,204 TA records without coordinates:
- **1,103** have a `postal_code` → eligible for Strategy B (postal-code block)
- **101** have no `postal_code` either → **unblockable** with any available key

### Postal-code density (blocking scale)

Top postal codes by TA record count (all TA records):

| CAP | Google anchor | TA (all) | TA no-coords | Worst-case postal block (no-coords × Google) |
|---|---|---|---|---|
| 20121 | 591 | 603 | 120 | 70,920 pairs |
| 20124 | 509 | 628 | 104 | 52,936 pairs |
| 20123 | 573 | 460 | 76 | 43,548 pairs |
| 20154 | 572 | 473 | 54 | 30,888 pairs |

Full naive postal-code blocking across ALL TA records (with and without coords) would
produce **350,000+ pairs for a single dense CAP** (591 Google × 603 TA for 20121). This
ruled out using postal-code blocking as the primary strategy.

### Phone and website coverage (key comparison signals)

| Signal | Google anchor | Tripadvisor |
|---|---|---|
| Phone | 8,408 / 10,054 (83.6%) | 6,795 / 7,539 (90.1%) |
| Website | 5,308 / 10,054 (52.8%) | 6,023 / 7,539 (79.9%) |

TheFork phone and website were deleted from the clean schema (0% coverage in scrape).

**TA no-coords records with phone or website**:
- Phone: 1,095 / 1,103 (99.3%) — nearly all have a phone
- Website: 1,027 / 1,103 (93.1%) — nearly all have a website

A spot-check of 5 random TA no-coords records against Google by exact phone string found
2 direct matches (`The Fish Ristopescheria`, `Stessa Direzione`). Phones are now
normalized by the clean transform; the actual fast-path match rate should be higher.

### TA `street` field structure

As of the `clean-transforms-er-prep` migration, `restaurants_clean_tripadvisor.street`
contains only the route name — the civic number and any venue-description suffix are
stripped by the transform and stored separately in `house_number`. All three clean
collections now emit a consistent route-only `street` field; no ER-level extraction
is needed.

---

## Functional Requirements

### Preprocessing

Preprocessing produces in-memory normalized strings for comparison; original document
fields are never mutated.

**Fields already normalized by the clean transforms (no ER-level work needed):**

- **Phone** (`restaurants_clean_google.phone`, `restaurants_clean_tripadvisor.phone`):
  already in compact E.164 format (formatting stripped; Italian national numbers prefixed
  with `+39`). Use directly for comparison — do not re-normalize.
- **Website** (`restaurants_clean_google.website`, `restaurants_clean_tripadvisor.website`):
  already scheme-stripped, `www.`-stripped, and trailing-slash-stripped. Use directly.
- **Street** (`restaurants_clean_tripadvisor.street`): the clean transform now extracts the
  route name before the first civic-number token. `street` is a clean route-only value
  in all three collections — no TA quirk to handle at ER time.

**Fields normalized at ER time (in-memory only):**

- **Name**: lowercase, collapse whitespace, strip punctuation (keep accented chars),
  expand common Italian abbreviations: `rist.` → `ristorante`, `trat.` → `trattoria`,
  `p.za`/`pza` → `piazza`.
- **Postal code**: no normalization needed — all three sources emit a 5-digit Italian CAP.

### Blocking

Blocking reduces the full Cartesian product (10,054 × 7,539 or 10,054 × 1,344) to a
tractable candidate set. Two strategies are used; the choice per record depends on
coordinate availability.

**Strategy A — Geo-proximity block (primary)**

Pair a Google anchor record with a source record when their Haversine distance ≤ 150 m.
Applied to:
- All Google × TF pairs (both sides have coords at ≥ 99.8%).
- Google × TA pairs where the TA record has `has_coordinates=true` (6,335 records, 84.1%).

Implementation note: a simple spatial index or a bounding-box pre-filter (±0.0015°
≈ 150 m at Milan's latitude) before Haversine avoids an O(N²) loop.

**Strategy B — Postal-code + name-prefix block (fallback)**

Applied **only** to TA records with `has_coordinates=false` and `postal_code != null`
(1,103 records).

Generating a full postal-code block naively produces 350,000+ candidate pairs for a
single dense CAP (e.g., CAP 20121: 120 TA no-coords × 591 Google = 70,920 pairs for that
CAP alone). To keep the candidate set tractable, pairs are generated only when both the
postal code matches **and** the normalized name shares at least one common token of ≥ 4
characters. This is a standard Sorted Neighbourhood approach.

101 TA records with neither coordinates nor postal code are labelled `UNBLOCKABLE` and
written to the output collection with `label="UNBLOCKABLE"` so they are auditable.

**Fast-path phone/website match (within any block)**

For TA records without coordinates (relying on Strategy B), phone and website carry
strong evidence. Before computing the composite score, check:
- If `phone` (Google) == `phone` (TA) → set `score=1.0`,
  `label=MATCH`, record `fast_path="phone"`.
- Else if `website` (Google) == `website` (TA) → same, `fast_path="website"`.

Fast-path pairs skip the composite score calculation. A fast-path MATCH still goes into
`entity_resolution_candidates` with all component fields for auditability.

### Comparison features

For each candidate pair (not fast-pathed) compute:

| Feature | Google field | TA field | TF field | Method |
|---|---|---|---|---|
| `name_sim` | `name` | `restaurant_name` | `restaurant_name` | `token_set_ratio` (rapidfuzz) / 100.0 → [0,1] |
| `geo_dist_m` | `lat`, `lon` | `lat`, `lon` | `lat`, `lon` | Haversine in metres; `None` when either side lacks coords |
| `street_sim` | `street` | `street` | `street` | `token_set_ratio` / 100.0 → [0,1] — all three sources emit a clean route-only value |
| `phone_match` | `phone` | `phone` | n/a | 1.0 if equal, 0.0 otherwise (null on either side → 0.0) |
| `website_match` | `website` | `website` | n/a | 1.0 if equal, 0.0 otherwise (null on either side → 0.0) |
| `postal_code_match` | `postal_code` | `postal_code` | `postal_code` | 1.0 if equal, 0.0 otherwise |

`cuisine_jaccard` (normalized Jaccard on cuisine token sets) is **diagnostic only** — stored in `components` but excluded from the composite score.

### Composite score and decision

Two weight regimes:

**Google × Tripadvisor** (phone and website available):

```
score = 0.40 * name_sim
      + 0.25 * geo_score        # 1 - min(geo_dist_m, 500) / 500; 0.0 if geo_dist_m is None
      + 0.10 * street_sim
      + 0.15 * phone_match
      + 0.10 * website_match
```

**Google × TheFork** (no phone or website):

```
score = 0.50 * name_sim
      + 0.35 * geo_score
      + 0.15 * street_sim
```

Decision thresholds are set empirically from a labeled mini-sample (see Acceptance
Criteria). Provisional defaults (to be tuned):

- `score >= dmax` → `MATCH`
- `score <= dmin` → `NON_MATCH`
- `dmin < score < dmax` → `UNCERTAIN`

`dmin` and `dmax` are stored in service config (not hard-coded) and documented in the
service README with the calibration procedure and chosen values.

### Output

Write to Mongo collection `entity_resolution_candidates` (upsert keyed on `_id`):

```json
{
  "_id": "<google_place_id>:<source_id>",
  "google_id": "<place_id>",
  "source": "tripadvisor" | "thefork",
  "source_id": "<ta_location_id | tf_id>",
  "block_source": "geo" | "postal_code" | "geo+postal_code" | "fast_path" | "unblockable",
  "fast_path": "phone" | "website" | null,
  "score": 0.87,
  "dmin": 0.40,
  "dmax": 0.85,
  "is_chain": false,
  "chain_brand": null,
  "chain_hardening": [],
  "components": {
    "name_sim": 0.92,
    "geo_dist_m": 43.2,
    "geo_score": 0.91,
    "street_sim": 0.85,
    "phone_match": 1.0,
    "website_match": 0.0,
    "postal_code_match": 1.0,
    "cuisine_jaccard": 0.33
  },
  "label": "MATCH",
  "llm_label": null,
  "_created_at": "<ISODate>"
}
```

**Upsert semantics**: a second run updates `score`, `components`, and `block_source`
only when `llm_label` is null (i.e., no LLM resolution has been applied yet). If
`llm_label` is set, the existing document is left untouched.

### CLI entrypoint

`uv run dataman-entity-resolve` with flags:

- `--source` (`tripadvisor` | `thefork` | `all`, default `all`)
- `--dry-run`: print candidate counts by block strategy and expected label distribution
  without writing to Mongo
- `--dmin FLOAT` / `--dmax FLOAT`: override config thresholds at runtime

### Service location

`services/transform/entity_resolution/` — same PEP 420 namespace package pattern as the
other transforms (`transform.entity_resolution`).

### Service README

`services/transform/entity_resolution/README.md` must document the end-to-end operational
workflow so anyone running the service for the first time knows what is manual and what is
automatic:

1. **First run — dry-run** (`uv run dataman-entity-resolve --dry-run`): automatic.
   Prints candidate counts by block strategy and projected label distribution for both
   pairings without writing to Mongo.
2. **Threshold calibration** — manual, one-time. Pull a sample of candidate pairs from the
   dry-run output, hand-label ≥ 50 known MATCHes and ≥ 50 known NON_MATCHes, inspect the
   score distribution, and choose `dmin` / `dmax`. Document the chosen values and the
   labeled sample size in the README.
3. **Production run** (`uv run dataman-entity-resolve`): automatic. Writes MATCH,
   NON_MATCH, UNCERTAIN, and UNBLOCKABLE records to `entity_resolution_candidates`.
4. **UNCERTAIN resolution** — separate LLM step (out of scope here). UNCERTAIN pairs sit
   in `entity_resolution_candidates` with `llm_label=null` until that step runs.

The README must also document where `dmin`/`dmax` are stored in config and how to override
them at runtime with `--dmin` / `--dmax`.

---

## Possible Edge Cases

- **TA street is pre-cleaned**: civic number and venue-description suffix are stripped by
  the `tripadvisor_clean` transform before ER runs. All three `street` fields are
  route-only; no extra extraction needed at ER time.
- **Dense postal-code blocks**: CAP 20121 alone has 591 Google × 120 TA no-coords records
  = 70,920 pairs. The name-token filter must fire before Haversine/score computation,
  not after — otherwise the computational cost is paid anyway.
- **Chain restaurants**: `McDonald's`, `Starbucks`, `Pizza Hut` produce many high
  `name_sim` pairs within the same CAP. Geo distance is the deciding feature; do not
  merge distinct chain outlets.
- **Fast-path phone collision**: Two different venues share a forwarding number or a
  management company number. Fast-path phone MATCHes should still store the full
  comparison components (name, geo, street) for post-hoc audit.
- **Null `geo_dist_m` in composite score**: Treated as 0.0 (`geo_score` = 0.0), which
  penalizes pairs that lack coordinate evidence. This is correct for TA no-coords records
  routed through Strategy B — their composite score relies mainly on name, phone, website.
- **TA records with only a name (no address, no phone, no website, no coords)**: Score
  will be `0.40 * name_sim` (TA regime). If name_sim < dmax, will land in UNCERTAIN or
  NON_MATCH — correct, since evidence is thin.
- **`tf_id` null**: TheFork records where the `-r<n>` token extraction failed. The
  `_id` should fall back to `source_id` (the full slug) to avoid key collisions.
- **TF `restaurant_url` vs venue `website`**: TF's `restaurant_url` is the TheFork
  listing URL (thefork.it/…), not the venue's own website. Never compare it against
  Google or TA `website`.

---

## Acceptance Criteria

- [ ] `uv run dataman-entity-resolve --dry-run` prints: candidate counts by block strategy
  (geo / postal_code / fast_path / unblockable), and projected label distribution, for
  each pairing — without writing to Mongo.
- [ ] All 101 TA unblockable records appear in `entity_resolution_candidates` with
  `label="UNBLOCKABLE"` and `block_source="unblockable"`.
- [ ] TA no-coords records that have a phone or website exact match against a Google
  record are written with `fast_path="phone"` or `fast_path="website"` and
  `label="MATCH"` without computing a composite score.
- [ ] For Google × TF: composite score uses the redistributed weight regime (no
  phone/website components).
- [ ] For Google × TA: phone and website components are included in the composite score.
- [ ] `postal_code` block is **only** applied to TA records with `has_coordinates=false`;
  TA records with coordinates go through the geo block exclusively.
- [ ] `street_sim` is computed directly against the `street` field from all three clean
  collections — no ER-level extraction is applied (civic number stripping is done by the
  `tripadvisor_clean` transform).
- [ ] A second run on unchanged input does not overwrite a document where `llm_label` is
  non-null.
- [ ] `--source thefork` produces no TA candidates; `--source tripadvisor` produces no TF
  candidates.
- [ ] A hand-labeled mini-sample of ≥ 50 known MATCH and ≥ 50 known NON_MATCH pairs is
  used to set `dmin` and `dmax`; the calibration procedure and values are documented in
  the service README.
- [ ] MATCH precision ≥ 0.90 and true-match recall into {MATCH ∪ UNCERTAIN} ≥ 0.97 on
  the labeled sample (true matches must almost never fall into NON_MATCH).

---

## Open Questions

- Should geo block and postal-code block ever both fire for the same TA pair, or should
  the geo block take exclusive priority when coordinates are present? (Current spec: geo
  takes priority; postal-code only for `has_coordinates=false`.)
- What is an acceptable UNCERTAIN bucket size? If > 20% of candidates are UNCERTAIN,
  should the LLM resolution batch be run inline or deferred?
- Should `entity_resolution_candidates` store NON_MATCH pairs, or only {MATCH, UNCERTAIN,
  UNBLOCKABLE}? Storing all three gives a complete audit trail but inflates collection size.
- Is 1:1 assignment (each Google record maps to at most one TA record, one TF record)
  enforced here, or in a downstream assignment step?
- For TA no-coords, 1,095/1,103 records have phone and 1,027/1,103 have website — should
  the fast-path be extended to all blocking strategies (not just Strategy B), or kept as
  a fallback-only path to avoid polluting geo-blocked pairs with phone-collision false
  positives?

---

## Out of Scope

- LLM-based resolution of UNCERTAIN pairs — separate spec/service.
- Unified dataset construction (`restaurants_integrated`) — depends on ER output.
- TA geocoding for the remaining 15.9% without coordinates — already a separate service.
- Cuisine vocabulary normalization — not a blocking dependency.
- Multi-source deduplication within a single platform (e.g. duplicate TA entries).
- Assigning a canonical `integrated_restaurant_id` — downstream of ER.

---

## Feature Testing Guidelines

Create `tests/transform/test_entity_resolution.py`. Cover without going heavy:

Note: phone/website normalization and TA street extraction are tested in
`tests/transform/test_er_prep.py` (clean-transform layer). ER tests focus on
blocking, scoring, labelling, and output semantics.

- **Name preprocessing**: ALL-CAPS recased, abbreviations expanded (`rist.` → `ristorante`),
  punctuation stripped, whitespace collapsed.
- **Geo blocking**: two records within 150 m produce a candidate pair; at 200 m they do not;
  records with null coordinates are excluded from geo block.
- **Postal-code + name-token block**: same CAP and shared 4+ char token → candidate pair;
  same CAP but no shared long token → no pair; different CAP → no pair.
- **Fast-path phone**: exact normalized phone match on either side → `label=MATCH`,
  `fast_path="phone"`, composite score not computed.
- **`block_source` tagging**: geo-only → `"geo"`; postal-code-only → `"postal_code"`;
  fast-path → `"fast_path"`; unblockable → `"unblockable"`.
- **Weight regimes**: TA pairing includes `phone_match` + `website_match` in score;
  TF pairing does not.
- **Decision thresholds**: score ≥ dmax → MATCH; ≤ dmin → NON_MATCH; between → UNCERTAIN.
- **Upsert idempotency**: second run on same input does not overwrite a non-null `llm_label`.
- **`--source` filtering**: `--source thefork` skips the TA pairing entirely.
