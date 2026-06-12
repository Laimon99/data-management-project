from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from transform.entity_resolution_llm.client import LlmClient, MockLlmClient, OpenAIResponsesClient
from transform.entity_resolution_llm.config import LlmERSettings
from transform.entity_resolution_llm.io import write_jsonl
from transform.entity_resolution_llm.policy import result_to_json
from transform.entity_resolution_llm.transform import (
    LlmERReport,
    dry_run_records,
    load_groups,
    run_groups,
)

Mode = Literal["dry-run", "mock", "openai"]


@dataclass
class LlmPipelineReport:
    mode: str
    apply: bool
    force: bool
    source: str
    limit: int | None
    output_jsonl: str | None
    llm: LlmERReport


def _client_for_mode(mode: Mode, settings: LlmERSettings) -> LlmClient:
    if mode == "mock":
        return MockLlmClient()
    if mode == "openai":
        return OpenAIResponsesClient(settings)
    raise ValueError("dry-run mode does not use an LLM client.")


def run_pipeline_collections(
    google_collection: Any,
    tripadvisor_collection: Any,
    thefork_collection: Any,
    candidates_collection: Any,
    llm_settings: LlmERSettings,
    *,
    mode: Mode = "dry-run",
    source: str = "all",
    apply: bool = False,
    force: bool = False,
    limit: int | None = None,
    output_jsonl: Path | None = None,
    llm_client: LlmClient | None = None,
) -> LlmPipelineReport:
    if mode == "dry-run" and apply:
        raise ValueError("--apply is not valid with --mode dry-run.")

    llm_report = LlmERReport(
        mode=mode,
        apply=apply,
        force=force,
        source=source,
        concurrency=llm_settings.llm_concurrency,
        output_jsonl=str(output_jsonl) if output_jsonl is not None else None,
    )
    groups = load_groups(
        google_collection,
        tripadvisor_collection,
        thefork_collection,
        candidates_collection,
        llm_settings,
        source=source,
        force=force,
        limit=limit,
        report=llm_report,
    )

    if mode == "dry-run":
        records = dry_run_records(groups, llm_settings)
    else:
        client = llm_client or _client_for_mode(mode, llm_settings)
        results = run_groups(
            groups,
            client,
            llm_settings,
            apply=apply,
            force=force,
            candidate_collection=candidates_collection,
            report=llm_report,
        )
        records = [result_to_json(result) for result in results]

    if output_jsonl is not None:
        write_jsonl(output_jsonl, records)

    return LlmPipelineReport(
        mode=mode,
        apply=apply,
        force=force,
        source=source,
        limit=limit,
        output_jsonl=str(output_jsonl) if output_jsonl is not None else None,
        llm=llm_report,
    )
