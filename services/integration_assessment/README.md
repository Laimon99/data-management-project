# Integration Assessment

Post-integration quality service for the Milan restaurant pipeline. It measures
entity-resolution classifier error, one-to-one link survival, and Tripadvisor
geocoding error against hand-labeled gold CSVs.

## Run

```bash
uv run integration-assessment
uv run integration-assessment \
  --in-calibration-gold-csv data/quality/entity_resolution_calibration_normal.csv \
  --in-calibration-gold-csv data/quality/entity_resolution_calibration_chains.csv \
  --gold-csv data/quality/my_out_of_sample_gold.csv
uv run integration-assessment export-sample \
  --output data/quality/integration_assessment/integration_gold_expand.csv --sample-size 200
```

Use `--in-calibration-gold-csv` for labels used to tune thresholds. Use
`--gold-csv` for out-of-sample labels that were never used for calibration. If
no `--gold-csv` is provided, the service falls back to evaluating on the
in-calibration files for backward compatibility.

## Outputs

- `data/quality/integration_assessment/integration_assessment_metrics.json`
- `data/quality/integration_assessment/integration_er_confusion.csv`
- `data/quality/integration_assessment/integration_errors.csv`
- `data/quality/integration_assessment/integration_geocoding_error.csv`
- `docs/post-integration-assessment.md`
- `report/post_integration/tables/*.tex`

The in-sample ER metrics reflect the shipped Mongo candidate labels and manual
LLM overrides. Cross-validation refits thresholds on held-out folds to estimate
generalization error.
