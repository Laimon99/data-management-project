# Post-Integration Assessment

Generated at: `2026-06-09T19:18:30.000656+00:00`

This report measures automated entity resolution, one-to-one link selection,
and Tripadvisor spatial enrichment against hand-labeled gold rows.

## Gold Standard

- Out-of-sample rows after CSV de-duplication: **300**.
- Out-of-sample evaluation rows used: **288**.
- Out-of-sample files: `data/quality/handlabel_for_post_int_assess.csv`.
- In-calibration rows: **600**.
- In-calibration files: `data/quality/entity_resolution_calibration_chains.csv`, `data/quality/entity_resolution_calibration_normal.csv`.
- Evaluation rows excluded because they also appeared in calibration files: **12**.

## Entity Resolution Classifier: Out-of-Sample

| Metric | Value |
|---|---:|
| MATCH precision | 96.8% |
| Strict MATCH recall | 71.7% |
| MATCH-or-UNCERTAIN kept recall | 100.0% |
| Accuracy | 66.0% |
| Uncertain rate | 33.0% |
| Gold rows missing from Mongo | 0 |

Five-fold cross-validation refits thresholds on the in-calibration gold rows
and scores the held-out fold inside that calibration set:

| CV metric | Mean | Std |
|---|---:|---:|
| MATCH precision | 96.2% | 5.0% |
| MATCH-or-UNCERTAIN kept recall | 98.3% | 2.4% |
| Uncertain rate | 10.8% | 1.7% |

## Entity Resolution Classifier: In-Calibration

| Metric | Value |
|---|---:|
| MATCH precision | 100.0% |
| Strict MATCH recall | 92.0% |
| MATCH-or-UNCERTAIN kept recall | 100.0% |
| Accuracy | 96.7% |
| Uncertain rate | 3.3% |

## End-to-End Survival

| Metric | Value |
|---|---:|
| Human-confirmed MATCH pairs | 127 |
| Classified as MATCH | 91 |
| Selected links | 88 |
| Integrated source blocks | 88 |
| Link survival rate | 69.3% |
| Integration survival rate | 69.3% |
| Dropped by 1:1 selection | 3 |
| Linked but missing source doc | 0 |

## Spatial Enrichment

| Metric | Value |
|---|---:|
| Tripadvisor gold MATCH distance rows | 46 |
| Median geocoding error | 10.1 m |
| p90 geocoding error | 40.5 m |
| p95 geocoding error | 52.6 m |
| Max geocoding error | 92.7 m |
| Within 50 m | 91.3% |
| Within 100 m | 100.0% |
| Within 250 m | 100.0% |
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

- Out-of-sample ER numbers use only rows passed with `--gold-csv`.
- In-calibration rows passed with `--in-calibration-gold-csv` are used for
  the calibration/CV block and are excluded from out-of-sample evaluation
  when the same candidate `_id` appears in both roles.
- Geocoding error among matches is truncated by the 150 m blocking radius.
  True matches geocoded farther away usually become ER recall loss, coordinate
  coverage failures, or UNBLOCKABLE candidates rather than large observed
  distance rows.
