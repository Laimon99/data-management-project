# Integrated Dataset Transform

This service turns entity-resolution candidates into the final MongoDB dataset used by
analysis queries.

It reads:

- `restaurants_clean_google`
- `restaurants_clean_tripadvisor`
- `restaurants_clean_thefork`
- `entity_resolution_candidates`

It writes:

- `entity_resolution_links`
- `restaurants_integrated`

## Decision Rule

The final candidate label is:

```text
effective_label = llm_label if llm_label is not null else label
```

Only `effective_label == "MATCH"` candidates can become resolved links. `NON_MATCH`,
`UNCERTAIN`, and `UNBLOCKABLE` candidates are not attached to the integrated dataset.

For each source independently, the service enforces one-to-one links:

- one Google restaurant can have at most one Tripadvisor link
- one Google restaurant can have at most one TheFork link
- one Tripadvisor record can link to at most one Google restaurant
- one TheFork record can link to at most one Google restaurant

When multiple `MATCH` candidates compete, priority is:

1. LLM-confirmed `MATCH`
2. higher deterministic score
3. phone/website fast path
4. shorter geographic distance
5. higher name similarity

## Build The Dataset

Run a preview without writing:

```bash
uv run dataman-build-integrated --dry-run
```

Build the final links and integrated collection:

```bash
uv run dataman-build-integrated --replace-destination
```

If you also need to run LLM adjudication immediately before this build, use the
recommended one-command runner:

```powershell
$env:DATAMAN_OPENAI_API_KEY="..."
powershell -ExecutionPolicy Bypass -File .\scripts\run_llm_matching_pipeline.ps1 `
  -Mode openai -Limit 10 -Apply `
  -OutputJsonl data/quality/llm_er_results_sample.jsonl
```

The PowerShell wrapper starts Docker Desktop/Mongo and prepares the data before running
the LLM branch. If MongoDB and `entity_resolution_candidates` already exist, the
lower-level equivalent is:

```bash
DATAMAN_OPENAI_API_KEY=... uv run dataman-llm-pipeline --mode openai --apply \
  --output-jsonl data/quality/llm_er_results.jsonl
```

Use `dataman-build-integrated` directly only when LLM decisions are already present in
`entity_resolution_candidates` and you only need to rebuild final links/dataset.

`--replace-destination` is recommended for final runs. It removes previous resolved
links for the selected source scope and rebuilds `restaurants_integrated` from the
current candidate collection, including LLM decisions.

Source-specific runs are available when only one source has changed:

```bash
uv run dataman-build-integrated --source tripadvisor --replace-destination
uv run dataman-build-integrated --source thefork --replace-destination
```

## Configuration

Environment variables use the `DATAMAN_` prefix:

| Variable | Default |
|---|---|
| `DATAMAN_MONGO_URI` | `mongodb://localhost:27017` |
| `DATAMAN_MONGO_DB` | `dataman` |
| `DATAMAN_GOOGLE_COLLECTION` | `restaurants_clean_google` |
| `DATAMAN_TRIPADVISOR_COLLECTION` | `restaurants_clean_tripadvisor` |
| `DATAMAN_THEFORK_COLLECTION` | `restaurants_clean_thefork` |
| `DATAMAN_CANDIDATES_COLLECTION` | `entity_resolution_candidates` |
| `DATAMAN_LINKS_COLLECTION` | `entity_resolution_links` |
| `DATAMAN_INTEGRATED_COLLECTION` | `restaurants_integrated` |

## Output Shape

`restaurants_integrated` is Google-seeded:

```text
one document = one operational Google dining venue
```

Core fields include:

- canonical Google name/address/coordinates
- source ids: `google_place_id`, `tripadvisor_location_id`, `thefork_id`
- normalized ratings: `google_rating_5`, `tripadvisor_rating_5`, `thefork_rating_5`
- raw TheFork rating: `thefork_rating_raw_10`
- review counts by platform
- platform flags: `has_google`, `has_tripadvisor`, `has_thefork`
- analytics fields: `rating_platform_count`, `rating_avg_5`, `rating_range_5`
- `match_provenance` copied from `entity_resolution_links`
- `integration_flags`, including LLM and ambiguity flags
