from __future__ import annotations

import argparse
from pathlib import Path

from .profiler import run_assessment
from .reporting import write_latex_tables, write_markdown_report


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m quality_assessment")
    subparsers = parser.add_subparsers(dest="command")
    profile = subparsers.add_parser("profile", help="Generate quality assessment outputs.")
    profile.add_argument(
        "--google-path",
        type=Path,
        default=Path("data/raw/google_places/restaurants_seed.jsonl"),
    )
    profile.add_argument(
        "--tripadvisor-path",
        type=Path,
        default=Path("data/raw/tripadvisor/tripadvisor_scraper_results.json"),
    )
    profile.add_argument(
        "--thefork-path",
        type=Path,
        default=Path("data/raw/thefork/thefork_milan_restaurants_enriched.json"),
    )
    profile.add_argument("--output-dir", type=Path, default=Path("data/quality"))
    profile.add_argument(
        "--markdown-report",
        type=Path,
        default=Path("docs/data-quality-assessment.md"),
    )
    profile.add_argument("--latex-tables-dir", type=Path, default=Path("report/tables"))
    profile.add_argument("--low-review-threshold", type=int, default=20)

    args = parser.parse_args()
    if args.command != "profile":
        parser.print_help()
        return

    payload = run_assessment(
        google_path=args.google_path,
        tripadvisor_path=args.tripadvisor_path,
        thefork_path=args.thefork_path,
        output_dir=args.output_dir,
        low_review_threshold=args.low_review_threshold,
    )
    write_markdown_report(payload, args.markdown_report)
    write_latex_tables(payload, args.latex_tables_dir)
    print("Quality assessment completed.")


if __name__ == "__main__":
    main()
