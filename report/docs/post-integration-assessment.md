# Post-Integration Assessment

Generated at: `2026-06-09T18:40:45.958013+00:00`

This report measures automated entity resolution, one-to-one link selection,
and Tripadvisor spatial enrichment against hand-labeled gold rows.

## Gold Standard

- Labeled rows used: **0**.
- Gold files: none loaded.

## Entity Resolution Classifier

| Metric | Value |
|---|---:|
| In-sample MATCH precision | n/a |
| In-sample strict MATCH recall | n/a |
| In-sample MATCH-or-UNCERTAIN kept recall | n/a |
| In-sample accuracy | n/a |
| In-sample uncertain rate | n/a |
| Gold rows missing from Mongo | 0 |

Five-fold cross-validation refits thresholds on each training fold and scores
the held-out rows:

| CV metric | Mean | Std |
|---|---:|---:|
| MATCH precision | n/a | n/a |
| MATCH-or-UNCERTAIN kept recall | n/a | n/a |
| Uncertain rate | n/a | n/a |

## End-to-End Survival

| Metric | Value |
|---|---:|
| Human-confirmed MATCH pairs | 0 |
| Classified as MATCH | 0 |
| Selected links | 0 |
| Integrated source blocks | 0 |
| Link survival rate | n/a |
| Integration survival rate | n/a |
| Dropped by 1:1 selection | 0 |
| Linked but missing source doc | 0 |

## Spatial Enrichment

| Metric | Value |
|---|---:|
| Tripadvisor gold MATCH distance rows | 0 |
| Median geocoding error | n/a m |
| p90 geocoding error | n/a m |
| p95 geocoding error | n/a m |
| Max geocoding error | n/a m |
| Within 50 m | n/a |
| Within 100 m | n/a |
| Within 250 m | n/a |
| Tripadvisor coordinate coverage | 84.0% |
| Tripadvisor records without coordinates | 1204 |
| Tripadvisor UNBLOCKABLE candidates | 101 |

## Generated Files

- `data/quality/integration_assessment/integration_assessment_metrics.json`: full structured payload.
- `data/quality/integration_assessment/integration_er_confusion.csv`: confusion matrix and breakdowns.
- `data/quality/integration_assessment/integration_errors.csv`: misclassified and dropped rows.
- `data/quality/integration_assessment/integration_geocoding_error.csv`: per-pair distance diagnostics.
- `report/post_integration/tables/*.tex`: report-ready LaTeX tables.

## Methodological Notes

- In-sample ER numbers are optimistic because the shipped thresholds were tuned
  on the same calibration labels; use the cross-validation block as the more
  honest estimate.
- Geocoding error among matches is truncated by the 150 m blocking radius.
  True matches geocoded farther away usually become ER recall loss, coordinate
  coverage failures, or UNBLOCKABLE candidates rather than large observed
  distance rows.
