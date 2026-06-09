# LLM Matching Pipeline

This is the convenience command for the work in `feature/llm-matching-simone`.

It runs, in order:

1. LLM adjudication over `entity_resolution_candidates`
2. resolved-link selection into `entity_resolution_links`
3. final integrated dataset construction into `restaurants_integrated`

It assumes the earlier pipeline stages have already produced:

- `restaurants_clean_google`
- `restaurants_clean_tripadvisor`
- `restaurants_clean_thefork`
- `entity_resolution_candidates`

It does **not** run scraping, raw loading, cleaning, or deterministic entity resolution.
Those stages must already be complete.

## Prerequisites

On Windows/PowerShell, the recommended full local command is the wrapper script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_llm_matching_pipeline.ps1 `
  -Mode dry-run -Limit 10
```

It starts Docker Desktop when needed, starts/reuses MongoDB, loads raw data, runs clean
transforms, rebuilds deterministic ER candidates, then runs `dataman-llm-pipeline`.
If a raw file is missing but the corresponding `restaurants_raw_*` collection already
contains data, the script skips that source load and continues.

If you run the lower-level commands manually, MongoDB must already be running:

```bash
docker compose up -d mongo
```

The real OpenAI mode also requires:

```powershell
$env:DATAMAN_OPENAI_API_KEY="..."
```

Do not commit `.env` files or API keys to GitHub.

## Safe Preview

```bash
uv run dataman-llm-pipeline --mode dry-run --limit 10
```

This builds LLM prompts and previews the integrated-dataset build without writing to
MongoDB. It assumes MongoDB is already running and previous data-preparation stages have
already been executed.

Full local preview from Mongo off:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_llm_matching_pipeline.ps1 `
  -Mode dry-run -Limit 10
```

## Offline End-To-End Test

```bash
uv run dataman-llm-pipeline --mode mock --limit 10 --apply
```

This does not call OpenAI. It uses the mock LLM, writes `llm_label` updates for the
limited sample, then rebuilds `entity_resolution_links` and `restaurants_integrated`.
Use this to verify the full write path without API cost.

Full local mock run from Mongo off:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_llm_matching_pipeline.ps1 `
  -Mode mock -Limit 10 -Apply
```

## Real OpenAI Run

PowerShell:

```powershell
$env:DATAMAN_OPENAI_API_KEY="..."
powershell -ExecutionPolicy Bypass -File .\scripts\run_llm_matching_pipeline.ps1 `
  -Mode openai -Limit 10 -Apply `
  -OutputJsonl data/quality/llm_er_results_sample.jsonl
```

Inspect the JSON report and the JSONL audit file before removing `--limit`.
If the default model is not enabled or has very low limits in your OpenAI project, pass a
model available in your project:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_llm_matching_pipeline.ps1 `
  -Mode openai -Limit 1 -Apply -Model gpt-4.1-mini `
  -OutputJsonl data/quality/llm_er_results_sample.jsonl
```

Full run:

```powershell
$env:DATAMAN_OPENAI_API_KEY="..."
powershell -ExecutionPolicy Bypass -File .\scripts\run_llm_matching_pipeline.ps1 `
  -Mode openai -NoLimit -Apply -Concurrency 3 `
  -OutputJsonl data/quality/llm_er_results.jsonl
```

`-Concurrency` controls how many source-venue groups are sent to the LLM in parallel.
Start with `2` or `3`; higher values can be faster but may hit OpenAI rate limits
depending on the project quota. The default is `1`, which preserves the old sequential
behavior. The lower-level CLI option is `--concurrency`, and the matching environment
variable is `DATAMAN_LLM_CONCURRENCY`.

`--apply` is intentionally explicit because it writes LLM decisions and rebuilds the
final MongoDB collections.

If data preparation has already been run and you only want to rerun the LLM branch, add
`-SkipPrepareData`.

## Options

| Option | Meaning |
|---|---|
| `--mode dry-run` | Build prompt/audit records and preview the integrated build without writing. |
| `--mode mock` | Use the offline mock LLM, useful for tests and demos without API cost. |
| `--mode openai` | Call the configured OpenAI model through the API. |
| `--apply` | Persist LLM decisions and rebuild final MongoDB collections. Required for writes. |
| `--limit N` | Process only the first N source-venue groups before rebuilding the dataset. |
| `-Model NAME` | PowerShell wrapper option to override the OpenAI model for this run. |
| `-Concurrency N` | PowerShell wrapper option to process N LLM groups in parallel. |
| `--source tripadvisor|thefork|all` | Restrict the run to one source or use both. |
| `--force` | Reprocess candidates that already have a non-null `llm_label`. |
| `--output-jsonl PATH` | Save prompts or LLM result records for auditability. |

## Output Collections

After a successful `--apply` run:

- `entity_resolution_candidates` contains LLM audit fields and `llm_label` decisions.
- `entity_resolution_links` contains one-to-one accepted platform links.
- `restaurants_integrated` contains the final Google-seeded integrated dataset.
