# Documentation index

## Start here

| Document | Purpose |
|---|---|
| [`RESULTS.md`](RESULTS.md) | Final dataset scale, Q1–Q11 findings, evidence, and caveats |
| [`PIPELINE.md`](PIPELINE.md) | End-to-end architecture and stage-by-stage data flow |
| [`../REPRODUCTION_OF_PROJECT.md`](../REPRODUCTION_OF_PROJECT.md) | Complete operational reproduction guide |
| [`PROJECT_HISTORY.md`](PROJECT_HISTORY.md) | Academic backup, cleanup rationale, and preservation details |
| [`../DATA_USAGE.md`](../DATA_USAGE.md) | Data provenance, third-party rights, and responsible reuse |

## Design and assessment

| Document | Purpose |
|---|---|
| [`storage-design.md`](storage-design.md) | MongoDB and ClickHouse evaluation and storage rationale |
| [`etl-design.md`](etl-design.md) | Load-layer design and historical implementation notes |
| [`schema-matching.md`](schema-matching.md) | Formal schema relations and conflict taxonomy |
| [`schema-correspondences.md`](schema-correspondences.md) | Engineering correspondences and integrated-schema mapping |
| [`data-quality-assessment.md`](data-quality-assessment.md) | Generated pre-integration quality assessment |
| [`post-integration-assessment.md`](post-integration-assessment.md) | Entity-resolution, link-survival, and geocoding assessment |
| [`dev-guide.md`](dev-guide.md) | Local development workflow and conventions |

Service-specific CLI and schema documentation is co-located under `services/`. Final
PDFs are indexed in [`deliverables/`](../deliverables/), and generated evidence is
indexed in [`artifacts/`](../artifacts/).

Historical course requirements, pitches, drafts, and the original README remain under
`requirements/`, `dump/`, and `archive/`; they are context, not current project status.
