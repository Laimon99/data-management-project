# Spec for research-questions-analysis
branch: feature/research-questions-analysis

## Summary

Answer the project's 7 research questions (4 main + 3 secondary, README §1) by
querying the flat analytics tables already loaded into **ClickHouse** by
`dataman-load-clickhouse` (`restaurants_integrated` plus the three
`restaurants_clean_*` tables).

The deliverable is a **Jupyter notebook** that connects to ClickHouse, runs one
analysis block per research question, renders the result tables and supporting
charts inline, and writes a short narrative answer for each question so the
output can be lifted directly into the final report (`report/final/`). All seven
questions are answerable from the current ClickHouse schema; the only caveat is
the *timeliness/"outdated information"* sub-part of Question 3, which has no
per-record collection timestamp in ClickHouse and must be answered with the
available proxies (review counts and per-platform presence) while the spec
explicitly notes the limitation.

This is the "Make at least 2 queries on the final dataset" deliverable from the
README TODO, expanded to cover all research questions, and it belongs to
pipeline Stage 7 (Analysis & results). It is a **read-only analytics layer** — it
must not modify MongoDB, ClickHouse tables, or any upstream collection.

### Research questions covered

Main:
1. How consistent are restaurant ratings across different online platforms?
2. Which restaurants show the highest disagreement between platforms?
3. Is rating inconsistency related to data quality issues (number of reviews,
   outdated information)?
4. Can low-quality or sparse data inflate perceived restaurant quality?

Secondary:
5. Are certain platforms systematically more optimistic/pessimistic?
6. Does inconsistency increase for smaller or less popular restaurants?
7. Does geographic location (center vs periphery) affect data completeness?

### Mapping of questions to ClickHouse data

| Q | Approach | Key columns |
|---|---|---|
| 1 | Distribution & summary stats of `rating_range_5`; share of restaurants within tolerance bands (e.g. ≤0.5, ≤1.0 star) among multi-platform venues | `rating_range_5`, `*_rating_5`, `rating_avg_5`, `platform_count` |
| 2 | Top-N restaurants ordered by `rating_range_5` desc, with per-platform ratings and city | `rating_range_5`, `*_rating_5`, `canonical_name`, `canonical_city` |
| 3 | Relate disagreement to review volume (min/total reviews) and platform coverage; document timeliness limitation | `rating_range_5`, `*_review_count`, `platform_count` |
| 4 | Compare ratings of sparse (<20 reviews) vs well-reviewed venues; show whether sparse venues skew high | `*_review_count`, `*_rating_5`, `rating_avg_5` |
| 5 | Per-platform mean rating and mean signed deviation from `rating_avg_5` (bias direction) over venues present on that platform | `*_rating_5`, `rating_avg_5` |
| 6 | Bin venues by popularity (review-count quantiles) and report mean/median `rating_range_5` per bin | `*_review_count`, `rating_range_5` |
| 7 | Center vs periphery split (see below); compare field-completeness coverage between zones using the `restaurants_clean_*` flag/coverage columns | `latitude`/`longitude`, `canonical_postal_code`, `has_website`, `has_phone`, `has_coordinates`, presence of rating/review fields |

### Center vs periphery definition (Q7)

Provide **both** cuts:
- **Primary — distance from Duomo:** Haversine distance from Piazza del Duomo
  (lat `45.4642`, lon `9.1900`) computed from `latitude`/`longitude`, binned into
  *center* (e.g. < 2 km) and *periphery* (≥ 2 km). The radius threshold is a
  documented, single-source constant that can be tuned.
- **Secondary — postal code / city grouping:** group by `canonical_postal_code`
  (and `canonical_city`) as an area proxy and report completeness per area.

## Functional Requirements

- A Jupyter notebook (e.g. `notebooks/research_questions_analysis.ipynb`) is the
  primary artifact, organized as one clearly-titled section per research question
  (Q1–Q7), each containing: the SQL query, the rendered result, at least one
  chart where it aids interpretation, and a short written answer.
- The notebook connects to ClickHouse using the same configuration convention as
  `load.clickhouse` (`DATAMAN_CLICKHOUSE_*` env vars, defaults `localhost:8123`,
  db `dataman`, user `default`), loading from `.env` when present.
- Queries read **only** from `restaurants_integrated`, `restaurants_clean_google`,
  `restaurants_clean_tripadvisor`, and `restaurants_clean_thefork`. No writes,
  no DDL, no truncation.
- All cross-platform consistency metrics (Q1, Q2, Q5, Q6) operate on the subset of
  restaurants present on **≥ 2 platforms** (`platform_count >= 2` / the relevant
  `rating_platform_count`), since single-platform rows have no disagreement signal.
  This filtering is explicit and stated in each relevant section.
- The "sparse data" threshold for Q4 reuses the project's existing reliability
  convention (review count < 20 = sparse, per README §4) as a named constant.
- The Duomo coordinates and the center radius for Q7 are defined once as named
  constants and reused.
- Each research question's section ends with a plain-language conclusion sentence
  suitable for pasting into the final report.
- A short markdown header cell documents prerequisites (ClickHouse running with
  the `analytics` profile and `dataman-load-clickhouse all` having been run) and
  how to execute the notebook end to end.
- Q3 explicitly documents that "outdated information" cannot be measured directly
  from ClickHouse (no per-record collection timestamp; `updated_at` is load time)
  and answers the data-quality link using review-volume and coverage proxies.

## Possible Edge Cases

- Restaurants present on only one platform: excluded from disagreement metrics;
  must not produce a spurious zero-range.
- `Nullable` rating / review-count columns: rows with a null rating on a platform
  must be excluded from that platform's averages rather than counted as 0.
- `rating_range_5` is null when fewer than two platform ratings exist — guard
  against it in ordering/filtering.
- Restaurants with missing/zero `latitude`/`longitude` (e.g. unresolved geo) must
  be excluded from the distance-based Q7 cut, not bucketed as distance 0.
- Empty `canonical_postal_code` rows excluded from the postal-code grouping (as in
  the README example query).
- TheFork native scale: use the normalized `thefork_rating_5` for cross-platform
  comparison, never `thefork_rating_raw_10`.
- ClickHouse unreachable: the notebook should fail with a clear message pointing to
  the `docker compose --profile analytics up -d clickhouse` step.
- Empty result sets (e.g. no venue exceeds a band) should render gracefully, not
  raise.

## Acceptance Criteria

- All 7 research questions have a dedicated, runnable section that produces a
  result table and a written answer.
- Q1, Q2, Q5, Q6 restrict to multi-platform restaurants and this is visible in the
  query/filter.
- Q2 reproduces (and extends) the README's "rating difference > 1 star" mandatory
  query, ordered by `rating_range_5` desc.
- Q7 produces both a distance-from-Duomo center/periphery completeness comparison
  and a postal-code/area completeness comparison.
- Q3 includes the documented timeliness limitation note.
- The notebook runs top to bottom without error against a populated ClickHouse
  instance, and performs no writes to any store.
- Configuration is read from `DATAMAN_CLICKHOUSE_*` env vars with the documented
  defaults; no credentials are hard-coded.
- Numeric thresholds (sparse=20, center radius, Duomo coords, tolerance bands) are
  defined as named constants in one place.

## Open Questions

- Charting library preference (matplotlib vs plotly) — plotly
- Exact center radius value for Q7 (default proposed: 2 km) — confirm before
  finalizing report numbers. - lets use multiple taling points - 2km around duomo vs others; known popular neigbourhoods (check readme of project for list and coords) vs others
- Whether any chosen result tables should also be exported as CSV into
  `report/final/` for the LaTeX report, or kept inline only. - yes, also latex tables are needed

## Out of Scope

- Modifying any ClickHouse table, MongoDB collection, or the loaders/transforms.
- Adding new columns to the ClickHouse schema or reloading data.
- Building a standalone Python console-script service or dashboard — delivery is a
  notebook only.
- Writing the final report prose/LaTeX itself (the notebook supplies inputs for it).
- Any new data acquisition, geocoding, or entity-resolution work.

## Feature Testing Guidelines

Create a test file under `/tests` (e.g. `tests/analysis/test_research_queries.py`)
covering, without going too heavy:

- The pure helper logic extracted from the notebook (kept in an importable module,
  e.g. `services/analysis/` or a thin `notebooks` helper) is unit-testable:
  - Haversine distance helper returns ~0 at the Duomo and a sane positive value for
    a known offset point.
  - Center/periphery classifier buckets a near-Duomo point as center and a far
    point as periphery given the radius constant.
  - Sparse-venue classifier (review count < 20) behaves at the boundary (19/20/21).
- A query-construction test asserting the multi-platform filter
  (`platform_count >= 2` / equivalent) is present in the consistency queries.
- Null-handling: helpers given a null rating/coordinate exclude the value rather
  than treating it as 0.
- Tests must not require a live ClickHouse connection (mock or test pure helpers
  only), consistent with the project's preference for source-level tests.
