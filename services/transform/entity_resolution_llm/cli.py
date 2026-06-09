from __future__ import annotations

import json
import logging
from dataclasses import asdict
from enum import Enum
from pathlib import Path

import typer
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from .client import MockLlmClient, OpenAIResponsesClient
from .config import LlmERSettings
from .io import write_jsonl
from .policy import result_to_json
from .transform import (
    LlmERReport,
    dry_run_records,
    load_groups,
    open_llm_collections,
    run_groups,
)

app = typer.Typer(add_completion=False, no_args_is_help=False)


class SourceOption(str, Enum):
    tripadvisor = "tripadvisor"
    thefork = "thefork"
    all = "all"


class ModeOption(str, Enum):
    dry_run = "dry-run"
    mock = "mock"
    openai = "openai"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command()
def adjudicate(
    mode: ModeOption = typer.Option(
        ModeOption.dry_run,
        "--mode",
        case_sensitive=False,
        help="dry-run builds prompts; mock runs offline; openai calls the API.",
    ),
    source: SourceOption = typer.Option(
        SourceOption.all,
        "--source",
        case_sensitive=False,
        help="Candidate source scope: tripadvisor, thefork, or all.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write LLM metadata and llm_label updates back to entity_resolution_candidates.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Include and overwrite candidates that already have a non-null llm_label.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-n",
        help="Only process the first N source-venue groups.",
    ),
    max_candidates: int | None = typer.Option(
        None,
        "--max-candidates",
        help="Override max Google candidates sent in each prompt.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Override DATAMAN_LLM_MATCH_MODEL for this run.",
    ),
    output_jsonl: Path | None = typer.Option(
        None,
        "--output-jsonl",
        help="Write prompt records or LLM result records to a JSONL audit file.",
    ),
) -> None:
    """Resolve UNCERTAIN ER candidates with an LLM/manual-compatible adjudication step."""

    _configure_logging()
    if mode == ModeOption.dry_run and apply:
        typer.echo("--apply is not valid with --mode dry-run.", err=True)
        raise typer.Exit(code=2)

    settings = LlmERSettings()
    if max_candidates is not None:
        settings.max_candidates = max_candidates
    if model is not None:
        settings.llm_match_model = model

    report = LlmERReport(
        mode=mode.value,
        apply=apply,
        force=force,
        source=source.value,
        output_jsonl=str(output_jsonl) if output_jsonl is not None else None,
    )

    mongo_client = None
    try:
        mongo_client, google, tripadvisor, thefork, candidates = open_llm_collections(settings)
        groups = load_groups(
            google,
            tripadvisor,
            thefork,
            candidates,
            settings,
            source=source.value,
            force=force,
            limit=limit,
            report=report,
        )

        if mode == ModeOption.dry_run:
            records = dry_run_records(groups, settings)
        else:
            client = (
                MockLlmClient()
                if mode == ModeOption.mock
                else OpenAIResponsesClient(settings)
            )
            results = run_groups(
                groups,
                client,
                settings,
                apply=apply,
                force=force,
                candidate_collection=candidates,
                report=report,
            )
            records = [result_to_json(result) for result in results]

        if output_jsonl is not None:
            write_jsonl(output_jsonl, records)
    except PyMongoError as exc:
        typer.echo(f"MongoDB error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except (ValidationError, ValueError) as exc:
        typer.echo(f"Error resolving LLM candidates: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        if mongo_client is not None:
            mongo_client.close()

    typer.echo(json.dumps(asdict(report), indent=2))
