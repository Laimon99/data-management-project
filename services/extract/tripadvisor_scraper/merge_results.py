# ruff: noqa: E501
"""
TRIPADVISOR PC-RESULTS MERGER
===========================================================
Merge Tripadvisor scraping output collected across multiple machines into one
set, deduplicate the records, and produce the list of URLs still left to scrape.

What it does:
  1. Merge every ``*results*.json`` in ``--input-dir`` into one deduplicated
     results file.
  2. Merge every ``*checkpoint*.json`` (union of ``processed_urls`` /
     ``failed_urls``).
  3. Redo list = the master URL list (``--url-list``) minus everything already
     done — i.e. what still needs scraping.

Records produced by the current scraper carry their own ``source_url``, so:
  - **Dedup** keys on ``source_url`` (one URL = one record, exact). Older records
    that predate the ``source_url`` field fall back to ``(restaurant_name,
    address)`` — name alone is not enough, since chain branches (e.g. "Pizzium",
    "Glory Pop") share a name.
  - **Redo** treats a URL as done if it appears in any checkpoint's
    ``processed_urls`` OR as a record's ``source_url``. So the merge is robust
    even if a machine's checkpoint is missing or corrupt — the records prove what
    was scraped.

Data safety: reads only from ``--input-dir`` / ``--url-list`` and writes only to
``--output-dir`` (refuses to write into the input dir or the live
``data/raw/tripadvisor`` directory). Review the output, then copy the files into
``data/raw/tripadvisor/`` to resume scraping.
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

# Output filenames (mirror the scraper's expected names).
RESULTS_FILENAME = "tripadvisor_scraper_results.json"
CHECKPOINT_FILENAME = "tripadvisor_checkpoint.json"
REDO_FILENAME = "redo_urls.txt"

# Top-level scraped fields, used to score record completeness during dedup.
RECORD_FIELDS = (
    "restaurant_name",
    "rating",
    "total_review",
    "cuisine_type",
    "price_range",
    "number_photo_uploaded",
    "address",
    "website",
    "phone_number",
    "email",
    "working_days_hours",
    "review",
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize(s) -> str:
    """Lowercase, strip diacritics, fold punctuation to spaces, collapse whitespace.

    Used to build a stable dedup key from free-text fields (handles Italian
    accents and inconsistent punctuation).
    """
    if not s:
        return ""
    folded = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(_NON_ALNUM_RE.sub(" ", folded).split())


def load_url_list(path: Path) -> list[str]:
    """Read the master URL list: one URL per line, blanks stripped, deduped (order kept)."""
    seen: set[str] = set()
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        url = line.strip()
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def load_json(path: Path):
    """Parse a JSON file; on any read/parse error, warn and return None (file skipped)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: skipping unreadable file {path.name}: {exc}", file=sys.stderr)
        return None


def completeness(record: dict) -> int:
    """Count non-empty top-level fields — higher means more complete."""
    return sum(1 for f in RECORD_FIELDS if record.get(f) not in (None, "", "NaN", [], {}))


def dedupe_key(record: dict):
    """Dedup key: the exact ``source_url`` when present, else ``(name, address)``."""
    url = record.get("source_url")
    if url:
        return ("url", url)
    return ("na", normalize(record.get("restaurant_name")), normalize(record.get("address")))


def dedupe(records: list[dict]) -> list[dict]:
    """Deduplicate by ``source_url`` (falling back to name+address), keeping the
    most complete record for each key."""
    best: dict[tuple, dict] = {}
    order: list[tuple] = []
    for rec in records:
        key = dedupe_key(rec)
        if key not in best:
            best[key] = rec
            order.append(key)
        elif completeness(rec) > completeness(best[key]):
            best[key] = rec
    return [best[k] for k in order]


def merge(input_dir: Path, master_urls: list[str]) -> dict:
    """Merge all result + checkpoint files; return merged records, checkpoint data,
    redo list, and per-file counts for the summary."""
    json_files = sorted(input_dir.glob("*.json"))

    records: list[dict] = []
    file_counts: list[tuple[str, int]] = []
    for path in json_files:
        if "results" not in path.name:
            continue
        data = load_json(path)
        if isinstance(data, list):
            records.extend(data)
            file_counts.append((path.name, len(data)))
        elif data is not None:
            print(f"WARNING: {path.name} is not a JSON array — skipped", file=sys.stderr)

    cp_processed: set[str] = set()
    failed: set[str] = set()
    n_checkpoints = 0
    for path in json_files:
        if "checkpoint" not in path.name:
            continue
        data = load_json(path)
        if isinstance(data, dict):
            cp_processed.update(data.get("processed_urls", []))
            failed.update(data.get("failed_urls", []))
            n_checkpoints += 1

    # A URL is "done" if a checkpoint says so OR a record carries it as source_url.
    record_urls = {r["source_url"] for r in records if r.get("source_url")}
    processed = cp_processed | record_urls
    # A URL that ultimately succeeded (has a record / is processed) is not failed.
    failed -= processed

    merged = dedupe(records)
    redo = [u for u in master_urls if u not in processed]

    return {
        "records": merged,
        "processed_urls": sorted(processed),
        "failed_urls": sorted(failed),
        "redo_urls": redo,
        "raw_count": len(records),
        "records_with_url": len(record_urls),
        "checkpoint_only_urls": len(cp_processed - record_urls),
        "file_counts": file_counts,
        "n_checkpoints": n_checkpoints,
    }


def write_outputs(output_dir: Path, result: dict) -> None:
    """Write merged results, unified checkpoint, and redo list to ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / RESULTS_FILENAME).write_text(
        json.dumps(result["records"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checkpoint = {
        "processed_urls": result["processed_urls"],
        "failed_urls": result["failed_urls"],
        "last_update": datetime.now().isoformat(),
    }
    (output_dir / CHECKPOINT_FILENAME).write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    redo_text = "\n".join(result["redo_urls"])
    (output_dir / REDO_FILENAME).write_text(redo_text + "\n" if redo_text else "", encoding="utf-8")


def print_summary(result: dict) -> None:
    """Print a concise merge summary to stdout."""
    print("\n=== MERGE SUMMARY ===\n")
    for name, count in result["file_counts"]:
        print(f"  {name}: {count} records")
    print(f"  checkpoints merged   : {result['n_checkpoints']}")
    print()
    print(f"Raw records (all files)   : {result['raw_count']}")
    print(f"  distinct source_urls    : {result['records_with_url']}")
    print(f"Unique after dedup        : {len(result['records'])}")
    print(f"Processed URLs            : {len(result['processed_urls'])}")
    print(f"  (checkpoint-only, no rec): {result['checkpoint_only_urls']}")
    print(f"Failed URLs               : {len(result['failed_urls'])}")
    print(f"Redo URLs left            : {len(result['redo_urls'])}")
    print()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tripadvisor-merge-results",
        description=(
            "Merge Tripadvisor results + checkpoints from multiple machines, dedupe "
            "records, and write the list of URLs still left to scrape. Reads only from "
            "--input-dir/--url-list and writes only to --output-dir."
        ),
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        type=Path,
        help="Folder with per-machine files (*results*.json and *checkpoint*.json).",
    )
    parser.add_argument(
        "--url-list",
        required=True,
        type=Path,
        help="Path to tripadvisor_list_restaurant.txt (the full target URL list).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Where merged outputs are written (created if absent). Must differ from --input-dir.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_dir: Path = args.input_dir
    output_dir: Path = args.output_dir

    if not input_dir.is_dir():
        print(f"ERROR: --input-dir does not exist: {input_dir}", file=sys.stderr)
        return 1
    if not args.url_list.is_file():
        print(f"ERROR: --url-list does not exist: {args.url_list}", file=sys.stderr)
        return 1

    out_resolved = output_dir.resolve()
    if out_resolved == input_dir.resolve():
        print("ERROR: --output-dir must differ from --input-dir.", file=sys.stderr)
        return 1
    if out_resolved == Path("data/raw/tripadvisor").resolve():
        print(
            "ERROR: --output-dir must not be the live data/raw/tripadvisor directory. "
            "Write to a separate folder, review it, then copy the files in manually.",
            file=sys.stderr,
        )
        return 1

    master_urls = load_url_list(args.url_list)
    if not master_urls:
        print("ERROR: --url-list is empty after stripping/deduping.", file=sys.stderr)
        return 1

    result = merge(input_dir, master_urls)
    if not result["records"] and not result["processed_urls"]:
        print(
            "ERROR: no result records and no checkpoints found. Nothing to merge.", file=sys.stderr
        )
        return 1

    write_outputs(output_dir, result)
    print_summary(result)
    print(f"Outputs written to: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
