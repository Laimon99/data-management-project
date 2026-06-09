# Entity Resolution Transform

Google is the anchor for both pairings:

- `restaurants_clean_google` x `restaurants_clean_tripadvisor`
- `restaurants_clean_google` x `restaurants_clean_thefork`

The service writes auditable candidate decisions to
`dataman.entity_resolution_candidates`. Tripadvisor and TheFork are not matched directly;
they are linked downstream through the shared Google `place_id`.

## Workflow

This workflow starts after raw data has been loaded and the three clean transforms have
produced:

- `restaurants_clean_google`
- `restaurants_clean_tripadvisor`
- `restaurants_clean_thefork`

If service code was edited before running console scripts, refresh the installed package
snapshot first:

```bash
uv sync --reinstall-package data-management-project
```

### 1. Generate A Baseline Candidate Collection

Preview candidate volume and provisional labels without writing:

```bash
uv run dataman-entity-resolve --dry-run
```

Write a fresh baseline candidate collection:

```bash
uv run dataman-entity-resolve --replace-destination
```

This writes `dataman.entity_resolution_candidates`. At this point every candidate has
an automatic `score`, effective `dmin`/`dmax`, provisional `label`, score `components`,
chain flags, and `llm_label=null`.

### 2. Export Normal-Venue Candidates For Hand Labeling

Export a sample excluding curated chain brands:

```bash
uv run dataman-er-calibrate export \
  --output data/quality/entity_resolution_calibration_normal.csv \
  --sample-size 400 \
  --source all \
  --chain-filter non_chain
```

**Hand-label point:** open `data/quality/entity_resolution_calibration_normal.csv` and
fill the `human_label` column with:

- `MATCH`
- `NON_MATCH`

Blank `human_label` rows are ignored by the analyzer. Do not edit `_id`, `source`,
`google_id`, `source_id`, `score`, `dmin`, `dmax`, `is_chain`, or component columns.

Analyze the labeled normal sample:

```bash
uv run dataman-er-calibrate analyze \
  data/quality/entity_resolution_calibration_normal.csv
```

Use the final `recommended_source_thresholds` block for:

- `--dmin-tripadvisor`
- `--dmax-tripadvisor`
- `--dmin-thefork`
- `--dmax-thefork`

### 3. Export Chain-Venue Candidates For Hand Labeling

Export a sample containing only curated chain brands:

```bash
uv run dataman-er-calibrate export \
  --output data/quality/entity_resolution_calibration_chains.csv \
  --sample-size 200 \
  --source all \
  --chain-filter chain
```

**Hand-label point:** open `data/quality/entity_resolution_calibration_chains.csv` and
fill `human_label` with `MATCH` or `NON_MATCH`. Chain rows should be judged at the
branch level: a McDonald's / La Piadineria / Spontini row is a match only when it is the
same physical branch, not merely the same brand.

Analyze the labeled chain sample:

```bash
uv run dataman-er-calibrate analyze \
  data/quality/entity_resolution_calibration_chains.csv
```

Use the final `recommended_chain_source_thresholds` block for:

- `--dmin-chain-tripadvisor`
- `--dmax-chain-tripadvisor`
- `--dmin-chain-thefork`
- `--dmax-chain-thefork`

### 4. Run The Final Calibrated Rewrite

Combine the normal thresholds and chain thresholds from the two analyzer reports:

```bash
uv run dataman-entity-resolve --replace-destination \
  --dmin-tripadvisor <normal-ta-dmin> \
  --dmax-tripadvisor <normal-ta-dmax> \
  --dmin-thefork <normal-tf-dmin> \
  --dmax-thefork <normal-tf-dmax> \
  --dmin-chain-tripadvisor <chain-ta-dmin> \
  --dmax-chain-tripadvisor <chain-ta-dmax> \
  --dmin-chain-thefork <chain-tf-dmin> \
  --dmax-chain-thefork <chain-tf-dmax>
```

After this run, `entity_resolution_candidates` is the calibrated candidate/evidence
collection. It is still not the final integrated dataset; the next integration step
will collapse `MATCH` candidates into resolved links and then populate
`restaurants_integrated`.

The calibration CSV is a reproducible manual artifact; the ER command does not read it
automatically. `llm_label` is reserved for a later UNCERTAIN-resolution step and is not
used for threshold calibration.

## CLI

```bash
uv run dataman-entity-resolve \
  [--source tripadvisor|thefork|all] \
  [--dry-run] \
  [--replace-destination] \
  [--dmin FLOAT] \
  [--dmax FLOAT] \
  [--dmin-tripadvisor FLOAT] \
  [--dmax-tripadvisor FLOAT] \
  [--dmin-thefork FLOAT] \
  [--dmax-thefork FLOAT] \
  [--dmin-chain-tripadvisor FLOAT] \
  [--dmax-chain-tripadvisor FLOAT] \
  [--dmin-chain-thefork FLOAT] \
  [--dmax-chain-thefork FLOAT]
```

`--source all` is the default. `--source tripadvisor` processes only Google x
Tripadvisor; `--source thefork` processes only Google x TheFork.

By default, reruns upsert candidates and leave existing documents with non-null
`llm_label` untouched. `--replace-destination` deletes existing candidate documents for
the selected source scope before writing regenerated candidates. With `--source all`,
this rewrites all ER candidates; with a single source, it rewrites only that source.
Replace mode is intentionally destructive and removes existing `llm_label` values in the
selected scope.

## Blocking

- Geo block: Haversine distance `<= DATAMAN_GEO_BLOCK_RADIUS_M` after a grid/bounding-box
  prefilter. Default radius: `150m`.
- Tripadvisor fallback block: only records without usable coordinates and with a postal
  code. The pair must share postal code and at least one normalized name token of length
  four or more.
- Tripadvisor records without coordinates and without postal code are written as
  `UNBLOCKABLE` audit records.

## Scoring

Defaults are provisional and should be calibrated with a labeled sample:

| Setting | Default |
|---|---:|
| `DATAMAN_DMIN` | `0.40` |
| `DATAMAN_DMAX` | `0.85` |
| `DATAMAN_GEO_BLOCK_RADIUS_M` | `150.0` |
| `DATAMAN_CHAIN_AUTO_MATCH_RADIUS_M` | `75.0` |

Optional source-specific environment overrides are also supported:

| Setting | Fallback |
|---|---:|
| `DATAMAN_DMIN_TRIPADVISOR` | `DATAMAN_DMIN` |
| `DATAMAN_DMAX_TRIPADVISOR` | `DATAMAN_DMAX` |
| `DATAMAN_DMIN_THEFORK` | `DATAMAN_DMIN` |
| `DATAMAN_DMAX_THEFORK` | `DATAMAN_DMAX` |
| `DATAMAN_DMIN_CHAIN_TRIPADVISOR` | `DATAMAN_DMIN_TRIPADVISOR` |
| `DATAMAN_DMAX_CHAIN_TRIPADVISOR` | `DATAMAN_DMAX_TRIPADVISOR` |
| `DATAMAN_DMIN_CHAIN_THEFORK` | `DATAMAN_DMIN_THEFORK` |
| `DATAMAN_DMAX_CHAIN_THEFORK` | `DATAMAN_DMAX_THEFORK` |

Tripadvisor score:

```text
0.40 * name_sim
+ 0.25 * geo_score
+ 0.10 * street_sim
+ 0.15 * phone_match
+ 0.10 * website_match
```

TheFork score:

```text
0.50 * name_sim
+ 0.35 * geo_score
+ 0.15 * street_sim
```

`cuisine_jaccard` is stored in `components` for diagnostics only and is excluded from the
score.

### Chain Hardening

The service marks curated repeated brands as chain venues using a fixed list derived from
the observed Google Milan distribution: `La Piadineria`, `McDonald's`, `Alice Pizza`,
`Panino Giusto`, `Bar Atlantic`, `Spontini`, `Burger King`, `KFC`,
`Cioccolatitaliani`, `California Bakery`, `Autogrill`, `Panificio Davide Longoni`,
`12oz`, `Flower Burger`, `Five Guys`, `Popeyes`, `Fratelli La Bufala`, `Burgez`,
`Marchesi 1824`, `Caffe Vergnano`, `I Love Poke`, `Miscusi`, `Old Wild West`,
`Poke House`, `Roadhouse`, `Rossopomodoro`, `Signorvino`, `Spun Tiramisu`,
`Starbucks`, `Street Smash Burgers`, and `VeroCaffe`.

For those brands, candidate documents store `is_chain=true` and `chain_brand`. The normal
150m geo block still generates pairs, but automatic `MATCH` labels are capped to
`UNCERTAIN` unless the geo distance is within `DATAMAN_CHAIN_AUTO_MATCH_RADIUS_M` or an
exact phone fast-path match exists. Website fast-path matching is suppressed for chains
because brand-level websites are often shared by multiple branches.

The analyzer reports chain-only threshold suggestions when the calibration CSV includes
the `is_chain` column. The full normal-vs-chain calibration sequence is documented in
the workflow section above.

## Output

Candidate pair ids use `<google_place_id>:<source_id>`. `source_id` is `ta_location_id`
or `tf_id`, falling back to the source document `_id` if needed.

Tripadvisor records that cannot be blocked use source-only ids:

```text
unblockable:tripadvisor:<source_id>
```

Existing documents with non-null `llm_label` are left untouched on rerun.
