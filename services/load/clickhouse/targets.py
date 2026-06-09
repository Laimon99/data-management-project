"""Target registry: maps a CLI selector to a ``TargetSpec``.

Mirrors ``load.mongo.sources`` — one frozen dataclass per target, a ``TARGETS``
dict, and a ``resolve`` helper.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .projections import (
    CLEAN_GOOGLE_COLUMNS,
    CLEAN_THEFORK_COLUMNS,
    CLEAN_TRIPADVISOR_COLUMNS,
    INTEGRATED_COLUMNS,
    project_clean_google,
    project_clean_thefork,
    project_clean_tripadvisor,
    project_integrated,
)
from .schema import (
    CLEAN_GOOGLE_DDL,
    CLEAN_THEFORK_DDL,
    CLEAN_TRIPADVISOR_DDL,
    INTEGRATED_DDL,
)

Projector = Callable[[dict[str, Any]], dict[str, Any] | None]


@dataclass(frozen=True)
class TargetSpec:
    """Describes one Mongo → ClickHouse load target.

    ``mongo_collection``  — source MongoDB collection name
    ``table``             — destination ClickHouse table name
    ``ddl``               — ``CREATE TABLE IF NOT EXISTS ...`` DDL (with ``{db}`` placeholder)
    ``projector``         — pure function mapping one Mongo doc → flat row dict | None
    ``column_order``      — ordered list of column names for ``clickhouse_connect.insert``
    """

    name: str
    mongo_collection: str
    table: str
    ddl: str
    projector: Projector
    column_order: list[str]


TARGETS: dict[str, TargetSpec] = {
    "integrated": TargetSpec(
        name="integrated",
        mongo_collection="restaurants_integrated",
        table="restaurants_integrated",
        ddl=INTEGRATED_DDL,
        projector=project_integrated,
        column_order=INTEGRATED_COLUMNS,
    ),
    "clean_google": TargetSpec(
        name="clean_google",
        mongo_collection="restaurants_clean_google",
        table="restaurants_clean_google",
        ddl=CLEAN_GOOGLE_DDL,
        projector=project_clean_google,
        column_order=CLEAN_GOOGLE_COLUMNS,
    ),
    "clean_tripadvisor": TargetSpec(
        name="clean_tripadvisor",
        mongo_collection="restaurants_clean_tripadvisor",
        table="restaurants_clean_tripadvisor",
        ddl=CLEAN_TRIPADVISOR_DDL,
        projector=project_clean_tripadvisor,
        column_order=CLEAN_TRIPADVISOR_COLUMNS,
    ),
    "clean_thefork": TargetSpec(
        name="clean_thefork",
        mongo_collection="restaurants_clean_thefork",
        table="restaurants_clean_thefork",
        ddl=CLEAN_THEFORK_DDL,
        projector=project_clean_thefork,
        column_order=CLEAN_THEFORK_COLUMNS,
    ),
}


def resolve(selector: str) -> list[TargetSpec]:
    """Map a CLI selector to one or more target specs.

    ``"all"`` expands to every registered target in definition order. An unknown
    selector raises ``ValueError`` listing the valid choices.
    """

    if selector == "all":
        return list(TARGETS.values())
    if selector in TARGETS:
        return [TARGETS[selector]]
    valid = ", ".join([*TARGETS.keys(), "all"])
    raise ValueError(f"Unknown target '{selector}'. Valid choices: {valid}.")
