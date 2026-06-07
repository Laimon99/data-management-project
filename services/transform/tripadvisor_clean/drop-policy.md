# Tripadvisor clean-layer drop policy

**Decision: the clean layer is flag-first. The only record dropped is one whose natural
key (`source_url`) is missing or blank.** Every other record is kept in
`restaurants_clean_tripadvisor` and annotated with `has_*` booleans + a `flags` list.

This mirrors `thefork_clean` (no default drops) rather than `google_clean` (which drops a
narrow inert-junk / non-dining class). The rationale is below, criterion by criterion.

## Why flag-first, not drop

The clean layer is a **reproducible product of a Mongo → Mongo transform**, and the raw
collection is the immutable audit trail. Dropping a record at clean time discards a venue
that downstream stages (entity resolution, the unified ratings table, the stage-5 quality
assessment) may legitimately want to reason about — including reasoning about *why* it is
low-quality. A flag preserves that information at near-zero cost; a drop destroys it.
Tripadvisor's missingness is also **field-systematic, not row-systematic** (EDA §B): there
is no "dead row" class the way Google had inert geographic-junk rows.

## Criteria considered (and why each is flagged, not dropped)

| Candidate "unusable" criterion | Prevalence | Decision |
|---|---|---|
| **Missing natural key** (`source_url` null/blank) | 0 observed | **DROP** — without a key the upsert cannot be idempotent (Mongo would mint an `ObjectId`, breaking re-run convergence). This is the sole drop. |
| Missing name | ~0 | **Flag-context only** — name is normalized; a blank name is rare and still a real venue row. |
| Missing rating (`no_rating`) | 15 (0.2%) | **Flag** — "not captured", not "unrated"; downstream completeness analysis needs to see it. |
| Rating present, 0 reviews (`rating_with_zero_reviews`) | 798 (10.6%) | **Flag** — a real venue with a thin base; relevant to the rating-quality analysis, not noise. |
| Missing address (`missing_address`) | 66 (0.9%) | **Flag** — geocoding will simply not run; the venue still has a rating/reviews. |
| Geocode failure (`geocode_not_found` / `missing_coordinates`) | geocode-dependent | **Flag** — a valid address can fail Nominatim transiently or for coverage reasons; a later full run may resolve it (resumable). Never drop on a geocode miss. |
| Low review count (`low_review`, `< 10`) | 2,841 (37.7%) | **Flag, count-only** — low-review filtering is a stage-5 *quality-improvement* lever applied at analysis time, deliberately not a clean-layer deletion. |
| No hours / no reviews (`no_hours` / `no_reviews`) | 32.4% / 11.4% | **Flag** — genuine absence of a rich field, not an unusable record. |

## Full-run convergence vs. drops (distinct concepts)

The transform deletes destination documents **only** to converge on the source key set:
on a **full run** (`limit is None`) any clean doc whose `source_url` no longer exists in
`restaurants_raw_tripadvisor` is removed (`stale_deleted`). A `--limit` run never deletes.
This is *re-run hygiene* (the venue vanished upstream), not a quality drop rule.

## Revisiting this decision

If a future analysis identifies a concrete, defensible "unusable" class (e.g. missing key
**and** missing name **and** no rating **and** no reviews — currently 0 rows), it can be
added as a narrow, documented default drop and surfaced in `CleanReport` (mirroring
`google_clean`'s `dropped_junk` / `dropped_non_dining`). Until such a class is shown to
exist and matter, the layer stays flag-first.
