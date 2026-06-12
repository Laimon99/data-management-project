from __future__ import annotations

import json
import logging
from dataclasses import asdict
from enum import Enum
from pathlib import Path

import typer
from pydantic import ValidationError
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from transform.entity_resolution_llm.config import LlmERSettings

from .transform import run_pipeline_collections

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
def run(
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
        help="Write LLM decisions back to entity_resolution_candidates.",
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
    concurrency: int | None = typer.Option(
        None,
        "--concurrency",
        min=1,
        max=16,
        help="Number of source-venue groups to process in parallel.",
    ),
    output_jsonl: Path | None = typer.Option(
        None,
        "--output-jsonl",
        help="Write prompt records or LLM result records to a JSONL audit file.",
    ),
) -> None:
    """Run LLM adjudication and write llm_label decisions to entity_resolution_candidates."""

    _configure_logging()
    if mode == ModeOption.dry_run and apply:
        typer.echo("--apply is not valid with --mode dry-run.", err=True)
        raise typer.Exit(code=2)

    llm_settings = LlmERSettings()
    if max_candidates is not None:
        llm_settings.max_candidates = max_candidates
    if model is not None:
        llm_settings.llm_match_model = model
    if concurrency is not None:
        llm_settings.llm_concurrency = concurrency

    client = None
    try:
        client = MongoClient(llm_settings.mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        db = client[llm_settings.mongo_db]
        report = run_pipeline_collections(
            db[llm_settings.google_collection],
            db[llm_settings.tripadvisor_collection],
            db[llm_settings.thefork_collection],
            db[llm_settings.candidates_collection],
            llm_settings,
            mode=mode.value,
            source=source.value,
            apply=apply,
            force=force,
            limit=limit,
            output_jsonl=output_jsonl,
        )
    except PyMongoError as exc:
        typer.echo(f"MongoDB error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except (ValidationError, ValueError) as exc:
        typer.echo(f"Error running LLM pipeline: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        if client is not None:
            client.close()

    typer.echo(json.dumps(asdict(report), indent=2))
