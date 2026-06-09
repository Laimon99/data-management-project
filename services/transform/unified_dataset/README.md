# Unified Dataset Transform

Stage-4 Mongo -> Mongo transform that materializes the final Google-seeded integrated
restaurant dataset.

```bash
uv run dataman-unify --dry-run
uv run dataman-unify --replace-destination
```

Inputs:

- `restaurants_clean_google`
- `restaurants_clean_tripadvisor`
- `restaurants_clean_thefork`
- `entity_resolution_candidates`

Outputs:

- `entity_resolution_links`
- `restaurants_integrated`

The service first collapses candidate pairs into one-to-one links using:

```text
effective_label = llm_label if llm_label is not null else label
```

Only `MATCH` links are selected. Tripadvisor and TheFork are processed independently,
so a Google entity may have no attached source, one attached source, or both attached
sources.

The integrated collection is hybrid nested: canonical identity/geography and comparable
ratings are top-level, while source-specific evidence remains under `sources.google`,
`sources.tripadvisor`, and `sources.thefork`.

The full effective schema, and the conflict-handling strategy applied to each top-level
field (mapped to the Bleiholder & Naumann ignoring/avoiding/resolution taxonomy), are
documented in [`integrated-dataset-schema.md`](integrated-dataset-schema.md).

