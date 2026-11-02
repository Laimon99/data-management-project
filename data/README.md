# Data

This directory keeps the public, reviewable evidence for the project without
shipping the complete acquired datasets in the showcase branch.

## What is public here

| Path | Contents |
|---|---|
| `samples/` | Small, curated samples with no review text, reviewer profiles, or contact fields |
| `quality/` | Aggregate quality metrics, calibration labels, and assessment results used by the reports |

The public integrated sample is deliberately narrow. It is useful for inspecting
the final schema and trying small examples, but it is not statistically
representative and must not be used to reproduce the published findings.

## Complete academic snapshot

The complete files that accompanied the course submission are preserved on the
Git branch [`backup/academic-submission-2026-08-27`](https://github.com/Laimon99/data-management-project/tree/backup/academic-submission-2026-08-27/data).
That branch is an archive, not the recommended starting point for new work.

The snapshot contains the raw acquisition outputs, processed entity-resolution
exports, and full ClickHouse analysis exports used by the team. Their presence in
Git history does not grant additional rights over third-party platform data; read
[`DATA_USAGE.md`](../DATA_USAGE.md) before downloading or reusing them.

## Local runtime layout

The pipeline recreates the following ignored directories:

```text
data/
├── raw/                 # extractor outputs for Google, Tripadvisor, and TheFork
├── processed/           # entity-resolution and integrated JSONL exports
├── analysis_export/     # full ClickHouse CSV/Parquet exports
├── exports/             # optional database exports
├── quality/             # tracked aggregate assessment evidence
└── samples/             # tracked public samples
```

The main load inputs are:

```text
data/raw/google_places/restaurants_seed.jsonl
data/raw/tripadvisor/tripadvisor_scraper_results.json
data/raw/thefork/thefork_milan_restaurants_enriched.json
```

To regenerate the downstream datasets, follow the
[`REPRODUCTION_OF_PROJECT.md`](../REPRODUCTION_OF_PROJECT.md) guide. Raw files are
append-only acquisition outputs and should never be edited by hand.

## Snapshot scale

The final academic run reported 10,808 Google Places records, 7,539 Tripadvisor
records, 1,344 TheFork records, and 10,054 integrated restaurants. Exact provenance
and quality figures are stored under `quality/` and discussed in the final report.
