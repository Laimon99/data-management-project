# analysis/queries — research-question SQL

Externalized ClickHouse SQL for the eleven research questions, exposed through
`analysis.queries` (loaded by name in `__init__.py`) and executed by the
`notebooks/q00…q11` via `run(...)`. Every query reads from the flat analytics tables
materialised by `services/load/clickhouse` — chiefly `restaurants_integrated`, with the
per-platform `restaurants_clean_*` tables for coverage/completeness facets.

Most questions have several SQL files (a summary + the row-level pulls behind each chart).

| Notebook / Q | SQL file(s) | Question → headline finding |
|---|---|---|
| `q00_overview` | `q0_platform_coverage.sql` | Baseline platform coverage across the seed (not a research question). |
| `q01_consistency` | `q1_summary`, `q1_histogram`, `q1_pairwise_agreement`, `q1_tolerance_bands` | How consistent are ratings across platforms? → Broad agreement, but pair-dependent: Google–TheFork agree tightly; Tripadvisor most often pulls ratings apart. |
| `q02_disagreement` | `q2_top_pair`, `q2_top_all_three` | Which restaurants disagree most? → Raw top gaps are sparse-review artefacts; gated at ≥100 reviews, ~15 venues still differ >1★ and Google always rates higher (upward tilt). |
| `q03_quality_link` | `q3_correlations`, `q3_binned`, `q3_scatter_rows` | Is inconsistency linked to data quality? → Spread vs review volume correlates negatively but weakly; volume is not the whole story. |
| `q04_sparse_data` | `q4_sparse_summary`, `q4_rating_rows`, `q4_rating_volume_rows` | Can sparse data inflate quality? → Not the mean, but volatility: <20-review venues are ~2–3× as dispersed and far more often extreme. |
| `q05_platform_bias` | `q5_platform_rows`, `q5_pairwise_differences` | Are platforms systematically optimistic/pessimistic? → Tripadvisor is systematically harsher; Google and TheFork sit on the generous side. |
| `q06_popularity` | `q6_popularity_bins` | Does inconsistency rise for less popular venues? → Yes — rating spread declines as Google review count rises. |
| `q07_location_completeness` | `q7_rows`, `q7_postal_completeness` | Does location affect completeness (and rating)? → Completeness falls with distance from the centre; central venues score higher on every facet but rate ~0.2★ lower (tourist core). |
| `q08_cuisine` | `q8_cuisine`, `q8_coverage`, `q8_cuisine_agreement`, `q8_price_rows` | Does consistency/level vary by cuisine? → After reconciling the cuisine field, broad-appeal categories rate lower and disagree most; seafood/Japanese/African rate top and most consistent. |
| `q09_price` | `q9_price_tier` | Do pricier restaurants rate higher / more consistently? → Higher tiers rate higher and disagree less (top tiers are small samples). |
| `q10_selection_effect` | `q10_rating_by_presence`, `q10_rating_by_coverage` | Are multi-platform venues rated differently? → Only marginally on rating, but strongly on popularity (median reviews ~3–7× from 1→3 platforms); presence is a popularity confounder. |
| `q11_photos` | `q11_photo_correlations`, `q11_photo_rows` | Does photo richness track popularity or rating? → Tracks popularity more than quality — correlates with review volume, only weakly with rating. |

Chart images for each question are exported to
`report/overleaf/images/research_questions/` (see its `MANIFEST.txt` for the
image → question mapping).
