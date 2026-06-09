# Entity Resolution LLM Adjudication

This service implements the LLM/manual review step after deterministic entity resolution.
It reads uncertain candidate pairs from MongoDB and writes audit metadata back to the same
candidate documents.

The service **does not generate new venues** and **does not modify deterministic evidence**
such as `score`, `components`, `label`, `google_id`, or `source_id`.

## Collections

Reads:

- `restaurants_clean_google`
- `restaurants_clean_tripadvisor`
- `restaurants_clean_thefork`
- `entity_resolution_candidates`

Updates:

- `entity_resolution_candidates`

Default input query:

```json
{"label": "UNCERTAIN", "llm_label": null}
```

The final downstream decision remains:

```text
effective_label = llm_label if llm_label is not null else label
```

## Candidate Grouping

Candidates are grouped by:

```text
source + source_id
```

The prompt receives one Tripadvisor/TheFork source venue and the top Google candidates
for that source venue, sorted by score, distance, and similarity. This lets the model
choose one candidate, reject all shown candidates, or keep the case uncertain.

## Modes

Dry-run builds prompt/audit records only:

```bash
uv run dataman-er-llm --mode dry-run --limit 5 --output-jsonl data/quality/llm_er_prompts.jsonl
```

Mock mode runs the full pipeline without an API key:

```bash
uv run dataman-er-llm --mode mock --limit 5 --output-jsonl data/quality/llm_er_mock.jsonl
```

Mock mode can also update MongoDB for a small smoke test:

```bash
uv run dataman-er-llm --mode mock --limit 5 --apply
```

Real OpenAI mode:

```bash
DATAMAN_OPENAI_API_KEY=... uv run dataman-er-llm --mode openai --apply --output-jsonl data/quality/llm_er_results.jsonl
```

To speed up real runs, process multiple source-venue groups in parallel:

```bash
DATAMAN_OPENAI_API_KEY=... uv run dataman-er-llm --mode openai --apply --concurrency 3
```

The default is `--concurrency 1`. Use `2` or `3` first; higher values can trigger
OpenAI rate limits depending on the project quota. The same value can be configured with
`DATAMAN_LLM_CONCURRENCY`.

Recommended full branch run: use this command when you want to run LLM adjudication and
then rebuild `entity_resolution_links` plus `restaurants_integrated` immediately after:

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

Use `dataman-er-llm` directly only when you want to inspect or debug LLM decisions
without rebuilding the final integrated dataset in the same command.

`--apply` is required for Mongo updates. Without it, the command only produces report
JSON and optional JSONL audit output.

## Safety

By default, candidates with a non-null `llm_label` are skipped. Use `--force` only when
you deliberately want to include and overwrite previous LLM decisions.

Accepted `MATCH` decisions are filtered by deterministic post-validation:

- confidence must be at least `DATAMAN_MATCH_CONFIDENCE_THRESHOLD` (default `0.85`);
- the selected candidate id must be present in the prompt candidate list;
- severe risk flags downgrade the result to `UNCERTAIN`;
- large distances without phone/website evidence downgrade to `UNCERTAIN`.

When the final decision is:

- `MATCH`: selected candidate gets `llm_label=MATCH`; the other prompt candidates get
  `llm_label=NON_MATCH`.
- `NON_MATCH`: all prompt candidates get `llm_label=NON_MATCH`.
- `UNCERTAIN`: `llm_label` stays null and only LLM audit metadata is stored.

## Updated Fields

The service writes fields such as:

```json
{
  "llm_label": "MATCH",
  "llm_status": "RESOLVED",
  "llm_decision": "MATCH",
  "llm_final_decision": "MATCH",
  "llm_selected_candidate_id": "<candidate _id>",
  "llm_model": "gpt-5.4-mini",
  "llm_confidence": 0.91,
  "llm_reason": "...",
  "llm_risk_flags": [],
  "llm_validation_notes": [],
  "llm_prompt_version": "v1",
  "llm_input_hash": "...",
  "llm_prompt_candidate_count": 3,
  "llm_total_candidate_count": 3,
  "llm_updated_at": "<UTC datetime>"
}
```

For unresolved cases, `llm_label` remains null and `llm_status` is set to `UNCERTAIN`.

## Full Reproduction

From a fresh checkout:

```bash
uv sync --extra dev
docker compose up -d mongo
uv run dataman-load all
uv run google-clean
uv run tripadvisor-clean
uv run thefork-clean
uv run dataman-entity-resolve --replace-destination \
  --dmin-tripadvisor 0.58 \
  --dmax-tripadvisor 0.63 \
  --dmin-thefork 0.86 \
  --dmax-thefork 0.94 \
  --dmin-chain-tripadvisor 0.49 \
  --dmax-chain-tripadvisor 0.52 \
  --dmin-chain-thefork 0.76 \
  --dmax-chain-thefork 0.79
uv run dataman-er-llm --mode dry-run --limit 10
DATAMAN_OPENAI_API_KEY=... uv run dataman-er-llm --mode openai --apply
```
