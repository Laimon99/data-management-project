import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .checkpoint import DetailCheckpoint
from .config import Settings
from .places_client import PermanentPlacesError, PlacesClient, TransientPlacesError
from .schema import merge_details
from .storage import SeedStore

_LOG = logging.getLogger(__name__)


@dataclass
class DetailReport:
    requested: int = 0
    enriched: int = 0
    skipped_already_done: int = 0
    skipped_unknown: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


def run_mode_detail(
    settings: Settings,
    store: SeedStore,
    client: PlacesClient,
    ckpt: DetailCheckpoint,
    *,
    place_ids: Iterable[str] | None = None,
) -> DetailReport:
    del settings  # currently no per-call tunables; reserved for future use
    report = DetailReport()
    target_ids = list(place_ids) if place_ids is not None else list(store.iter_place_ids())

    for pid in target_ids:
        report.requested += 1
        if ckpt.has(pid):
            report.skipped_already_done += 1
            continue
        existing = store.get(pid)
        if existing is None:
            report.skipped_unknown += 1
            _LOG.warning("place_id %s not in seed store; skipping detail fetch", pid)
            continue
        try:
            raw = client.place_details(pid)
        except (TransientPlacesError, PermanentPlacesError) as exc:
            _LOG.warning("place_id %s detail fetch failed: %s", pid, exc)
            report.errors.append({"place_id": pid, "reason": str(exc)})
            continue

        absent = [k for k, v in raw.items() if v is None]
        if absent:
            _LOG.info(
                "place_id %s: %d null detail fields (sample: %s)",
                pid,
                len(absent),
                absent[:10],
            )

        merged = merge_details(existing, raw)
        store.upsert(merged)
        ckpt.add(pid)
        report.enriched += 1

    return report
