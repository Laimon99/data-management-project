from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


def write_markdown_report(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Data Quality Assessment",
        "",
        f"Generated at: `{payload['generated_at']}`",
        "",
        "This document is generated from the raw acquisition outputs. It is intended as a",
        "reproducible basis for the final project report; conclusions and narrative should",
        "still be reviewed by the group.",
        "",
        "Scope: this is a **pre-integration baseline**. It assesses the three source",
        "datasets after acquisition and before entity matching or unified-table creation.",
        "",
        "## Quality Dimensions",
        "",
        "- **Completeness**: percentage of non-missing values per relevant field.",
        "- **Critical completeness**: same calculation restricted to fields required",
        "  for matching, rating analysis, and spatial integration.",
        "- **Validity / consistency**: present values matching source-specific formats",
        "  such as rating scale, review-count type, URL/email/phone shape, price format,",
        "  timestamp format, and numeric fields.",
        "- **Uniqueness**: duplicate source identifiers and possible duplicate normalized",
        "  name/address pairs.",
        "- **Timeliness**: refreshability based on the collection duration required by",
        "  each source; timestamp coverage is reported separately as supporting evidence.",
        f"- **Reliability**: records with review count below `{payload['low_review_threshold']}`",
        "  are flagged as sparse evidence for rating interpretation.",
        "- **Overall score**: weighted roll-up of critical completeness, validity,",
        "  spatial readiness, uniqueness, timeliness, and review-count reliability.",
        "",
        "## Metric Definitions",
        "",
    ]
    lines.extend(markdown_metric_definitions(payload))
    lines.extend(
        [
            "",
            "## Cross-Source Summary",
            "",
        ]
    )
    lines.extend(markdown_summary_table(payload))
    lines.extend(["", "## Pre-Integration Visual Diagnostics", ""])
    lines.extend(markdown_visual_diagnostics(payload))
    lines.extend(["", "## Quality Score Model", ""])
    lines.extend(markdown_score_model(payload))
    lines.extend(["", "## Comparative Findings", ""])
    lines.extend(markdown_comparative_findings(payload))
    lines.extend(["", "## Quality Improvement Actions", ""])
    lines.extend(markdown_improvement_actions(payload))
    lines.extend(["", "## Source-Specific Assessment", ""])
    for source in payload["sources"]:
        lines.extend(markdown_source_section(source))
    lines.extend(
        [
            "## Generated Files",
            "",
            "- `data/quality/source_quality_metrics.json`: full structured metrics.",
            "- `data/quality/field_coverage.csv`: field-level completeness table.",
            "- `data/quality/anomalies.csv`: record-level quality flags.",
            "- `data/quality/source_quality_scores.csv`: weighted quality score components.",
            "- `report/tables/metric_definitions.tex`: LaTeX metric formula table.",
            "- `report/tables/source_summary.tex`: LaTeX source summary table.",
            "- `report/tables/source_quality_scores.tex`: score breakdown table.",
            "- `report/tables/visual_quality_scores.tex`: score bar chart.",
            "- `report/tables/visual_score_components.tex`: component bar chart.",
            "- `report/tables/visual_coverage_heatmap.tex`: core coverage heatmap.",
            "- `report/tables/visual_anomaly_profile.tex`: anomaly profile chart.",
            "- `report/tables/improvement_actions.tex`: report-ready remediation plan.",
            "- `report/tables/source_comparison.tex`: LaTeX comparison table.",
            "- `report/tables/*_detail.tex`: source-specific LaTeX sections.",
            "- `report/tables/*_field_coverage.tex`: source-specific field coverage tables.",
            "- `report/tables/field_coverage.tex`: complete LaTeX field coverage table.",
            "",
            "## Methodological Notes",
            "",
            "Raw files are never overwritten. Platform-specific values are normalized only for",
            "quality assessment: textual missing markers such as `NaN` are treated as missing,",
            "Tripadvisor comma-decimal ratings are parsed as floats, review-count strings are",
            "parsed as integers, and TheFork ratings remain on their native 0-10 scale.",
            "For cross-platform analysis, TheFork can later be projected to a 0-5 scale by",
            "dividing by two, but this assessment keeps the original source scale.",
            "This baseline should be rerun after cleaning/enrichment so before/after",
            "changes in completeness, validity, spatial readiness, and reliability are",
            "measured with the same formulas.",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def markdown_metric_definitions(payload: dict[str, Any]) -> list[str]:
    target_hours = payload["sources"][0]["summary"].get("refresh_target_hours", 48.0)
    return [
        "All component scores are percentages where **100% is better**. Quality flags",
        "are warning counts, not a positive score.",
        "",
        "| Metric | Formula / definition | Reading |",
        "|---|---|---|",
        (
            "| Completeness | `100 * present relevant field values / expected relevant field "
            "values` | Average coverage over all profiled fields. |"
        ),
        (
            "| Critical completeness | `100 * present critical field values / expected "
            "critical field values` | Coverage of identifiers, name/address, rating, "
            "review-count, and coordinates where required. |"
        ),
        (
            "| Validity | `100 * valid present values / present values checked by validators` "
            "| Source-specific format checks over present values; missingness is handled by "
            "completeness. |"
        ),
        (
            "| Spatial readiness | `100 * records with valid latitude/longitude pair / records` "
            "| Readiness for geospatial matching. |"
        ),
        (
            "| Timeliness | `max(0, 100 * (1 - collection_duration_hours / "
            "refresh_target_hours))` | Refreshability against the current "
            f"{fmt_float(target_hours)}h target. |"
        ),
        (
            "| Reliability | `100 * records with review_count >= low_review_threshold / "
            "records` | Share of records whose rating is supported by enough reviews. |"
        ),
        (
            "| Uniqueness | `100 - 100 * duplicate flags / records` | Penalizes duplicate "
            "source identifiers and duplicate normalized name/address keys. |"
        ),
        (
            "| Quality flags | Record-level warnings; `flags_per_100 = 100 * flags / records` "
            "| Diagnostic log for cleaning/enrichment, not an automatic deletion list. |"
        ),
        "",
        (
            "`timestamp_coverage_pct` is reported separately because record-level timestamps "
            "are useful evidence, but they are not the timeliness score itself."
        ),
    ]


def markdown_summary_table(payload: dict[str, Any]) -> list[str]:
    lines = [
        "| Source | Records | Quality score | Completeness | Critical | Validity | Spatial | "
        "Timeliness | Reliable reviews | Flags / 100 records |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for source in payload["sources"]:
        summary = source["summary"]
        lines.append(
            "| {source} | {records} | {score} | {complete} | {critical} | "
            "{validity} | {spatial} | {timeliness} | {reliability} | {flags} |".format(
                source=source["source"],
                records=source["record_count"],
                score=fmt_pct(summary["overall_quality_score_pct"]),
                complete=fmt_pct(summary["completeness_score_pct"]),
                critical=fmt_pct(summary["critical_completeness_score_pct"]),
                validity=fmt_pct(summary["validity_score_pct"]),
                spatial=fmt_pct(summary["spatial_readiness_score_pct"]),
                timeliness=fmt_pct(summary["timeliness_score_pct"]),
                reliability=fmt_pct(summary["reliability_score_pct"]),
                flags=fmt_float(anomaly_flags_per_100(source)),
            )
        )
    return lines


def markdown_visual_diagnostics(payload: dict[str, Any]) -> list[str]:
    best_quality = max(
        payload["sources"],
        key=lambda source: source["summary"]["overall_quality_score_pct"],
    )
    weakest_quality = min(
        payload["sources"],
        key=lambda source: source["summary"]["overall_quality_score_pct"],
    )
    return [
        "The PDF report includes generated visual diagnostics for the pre-integration",
        "baseline: weighted score bars, component bars, a core-field coverage heatmap,",
        "and an anomaly profile by source. These charts are regenerated by the same",
        "script that refreshes the metrics.",
        "",
        f"- Strongest pre-integration source by weighted score: **{best_quality['source']}** "
        f"({fmt_pct(best_quality['summary']['overall_quality_score_pct'])}).",
        f"- Weakest pre-integration source by weighted score: **{weakest_quality['source']}** "
        f"({fmt_pct(weakest_quality['summary']['overall_quality_score_pct'])}).",
    ]


def markdown_score_model(payload: dict[str, Any]) -> list[str]:
    lines = [
        "The overall score is not a generic average of all available fields. It uses",
        "a fixed weighted model aligned with the integration task:",
        "",
        "Average completeness is reported in the summary, but the weighted score uses",
        "critical completeness so optional metadata does not dominate identifiers,",
        "ratings, review counts, and coordinates.",
        "",
        "| Component | Weight | Interpretation |",
        "|---|---:|---|",
        (
            "| Critical completeness | 25% | fields needed for identity, ratings, "
            "review counts, and coordinates |"
        ),
        (
            "| Validity | 20% | present values matching expected source-specific formats "
            "across the profiled fields |"
        ),
        "| Spatial readiness | 15% | records with complete latitude/longitude pairs |",
        (
            "| Uniqueness | 15% | absence of duplicate source identifiers and "
            "duplicate name/address keys |"
        ),
        (
            "| Timeliness | 10% | source refreshability from collection duration versus "
            "the refresh target |"
        ),
        (
            "| Reliability | 15% | records whose review count is at least the "
            "sparse-evidence threshold |"
        ),
        "",
        (
            "| Source | Score | Critical | Validity | Spatial | Uniqueness | "
            "Timeliness | Reliability |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for source in payload["sources"]:
        summary = source["summary"]
        lines.append(
            "| {source} | {score} | {critical} | {validity} | {spatial} | "
            "{unique} | {time} | {reliable} |".format(
                source=source["source"],
                score=fmt_pct(summary["overall_quality_score_pct"]),
                critical=fmt_pct(summary["critical_completeness_score_pct"]),
                validity=fmt_pct(summary["validity_score_pct"]),
                spatial=fmt_pct(summary["spatial_readiness_score_pct"]),
                unique=fmt_pct(summary["uniqueness_score_pct"]),
                time=fmt_pct(summary["timeliness_score_pct"]),
                reliable=fmt_pct(summary["reliability_score_pct"]),
            )
        )
    return lines


def markdown_comparative_findings(payload: dict[str, Any]) -> list[str]:
    sources = payload["sources"]
    largest = max(sources, key=lambda source: source["record_count"])
    best_quality = max(
        sources,
        key=lambda source: source["summary"]["overall_quality_score_pct"],
    )
    weakest_quality = min(
        sources,
        key=lambda source: source["summary"]["overall_quality_score_pct"],
    )
    best_completeness = max(
        sources,
        key=lambda source: source["summary"]["completeness_score_pct"],
    )
    weakest_completeness = min(
        sources,
        key=lambda source: source["summary"]["completeness_score_pct"],
    )
    best_critical = max(
        sources,
        key=lambda source: source["summary"]["critical_completeness_score_pct"],
    )
    sparsest = max(
        sources,
        key=lambda source: source["summary"]["low_review_pct_of_valid_reviews"],
    )
    most_flags = max(sources, key=anomaly_flags_per_100)
    weakest_timeliness = min(
        sources,
        key=lambda source: source["summary"]["timeliness_score_pct"],
    )
    coordinate_ready = [
        source["source"]
        for source in sources
        if source["summary"]["valid_coordinate_pair_pct"] >= 95
    ]
    lines = [
        f"- Largest source by volume: **{largest['source']}** "
        f"with **{largest['record_count']}** records.",
        f"- Highest weighted quality score: **{best_quality['source']}** "
        f"({fmt_pct(best_quality['summary']['overall_quality_score_pct'])}).",
        f"- Lowest weighted quality score: **{weakest_quality['source']}** "
        f"({fmt_pct(weakest_quality['summary']['overall_quality_score_pct'])}).",
        f"- Highest average field completeness: **{best_completeness['source']}** "
        f"({fmt_pct(best_completeness['summary']['completeness_score_pct'])}).",
        f"- Weakest average field completeness: **{weakest_completeness['source']}** "
        f"({fmt_pct(weakest_completeness['summary']['completeness_score_pct'])}).",
        f"- Highest critical-field completeness: **{best_critical['source']}** "
        f"({fmt_pct(best_critical['summary']['critical_completeness_score_pct'])}).",
        "- Coordinate-ready sources for geospatial integration: "
        + ", ".join(f"**{name}**" for name in coordinate_ready)
        + ".",
        f"- Highest share of sparse review evidence: **{sparsest['source']}** "
        f"({fmt_pct(sparsest['summary']['low_review_pct_of_valid_reviews'])} "
        "of valid review counts).",
        f"- Highest density of quality flags: **{most_flags['source']}** "
        f"({fmt_float(anomaly_flags_per_100(most_flags))} flags per 100 records).",
        f"- Weakest source refreshability: **{weakest_timeliness['source']}** "
        f"({fmt_pct(weakest_timeliness['summary']['timeliness_score_pct'])}).",
        "- Tripadvisor currently has no coordinates in the raw file, so its geospatial",
        "  integration depends on the enrichment step before final matching.",
        "- Tripadvisor's lower raw score is expected at this stage: the file has no",
        "  coordinates, no record-level timestamps, and many sparse pages with zero or",
        "  low review counts. Cleaning/enrichment should be measured by rerunning the",
        "  same assessment after preprocessing.",
    ]
    return lines


def markdown_improvement_actions(payload: dict[str, Any]) -> list[str]:
    lines = [
        "| Priority | Scope | Action | Expected effect |",
        "|---:|---|---|---|",
    ]
    for priority, scope, action, effect in improvement_actions(payload):
        lines.append(f"| {priority} | {scope} | {action} | {effect} |")
    return lines


def markdown_source_section(source: dict[str, Any]) -> list[str]:
    summary = source["summary"]
    lines = [
        f"### {source['source']}",
        "",
        source_role(source["source"]),
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Records assessed | {source['record_count']} |",
        f"| Overall quality score | {fmt_pct(summary['overall_quality_score_pct'])} |",
        f"| Average field completeness | {fmt_pct(summary['completeness_score_pct'])} |",
        f"| Critical-field completeness | {fmt_pct(summary['critical_completeness_score_pct'])} |",
        f"| Validity score | {fmt_pct(summary['validity_score_pct'])} |",
        f"| Uniqueness score | {fmt_pct(summary['uniqueness_score_pct'])} |",
        f"| Timeliness score | {fmt_pct(summary['timeliness_score_pct'])} |",
        f"| Collection duration | {fmt_hours(summary['collection_duration_hours'])} |",
        f"| Timestamp coverage | {fmt_pct(summary['timestamp_coverage_pct'])} |",
        f"| Reliability score | {fmt_pct(summary['reliability_score_pct'])} |",
        (
            f"| Format values checked | {summary['format_valid_value_count']} / "
            f"{summary['format_checked_value_count']} valid |"
        ),
        f"| Native rating average | {fmt_optional(summary['rating_avg'])} |",
        f"| Comparable rating average (0-5) | {fmt_optional(comparable_rating_avg(source))} |",
        f"| Valid review counts | {summary['valid_review_count']} "
        f"({fmt_pct(summary['valid_review_count_pct'])}) |",
        f"| Low-review records | {summary['low_review_records']} "
        f"({fmt_pct(summary['low_review_pct_of_valid_reviews'])}) |",
        f"| Valid coordinate pairs | {summary['valid_coordinate_pair_count']} "
        f"({fmt_pct(summary['valid_coordinate_pair_pct'])}) |",
        f"| Latest source timestamp | {fmt_optional_text(summary['latest_timestamp'])} |",
        f"| Data age in days | {fmt_optional(summary['data_age_days'])} |",
        f"| Quality flags | {summary['anomaly_count']} "
        f"({fmt_float(anomaly_flags_per_100(source))} per 100 records) |",
        "",
        "Weakest field coverage:",
        "",
        "| Field | Present | Missing | Coverage |",
        "|---|---:|---:|---:|",
    ]
    for item in lowest_coverage_fields(source, limit=7):
        lines.append(
            f"| `{item['field']}` | {item['present']} | {item['missing']} | "
            f"{fmt_pct(item['coverage_pct'])} |"
        )
    lines.extend(["", "Most frequent quality flags:", "", "| Issue type | Count |", "|---|---:|"])
    for issue_type, count in anomaly_type_counts(source, limit=6):
        lines.append(f"| `{issue_type}` | {count} |")
    lines.extend(["", "Interpretation:", ""])
    lines.extend(f"- {note}" for note in interpretation_notes(source))
    lines.append("")
    return lines


def write_latex_tables(payload: dict[str, Any], tables_dir: Path) -> None:
    tables_dir.mkdir(parents=True, exist_ok=True)
    (tables_dir / "metric_definitions.tex").write_text(
        metric_definitions_table(payload),
        encoding="utf-8",
    )
    (tables_dir / "source_summary.tex").write_text(
        source_summary_table(payload),
        encoding="utf-8",
    )
    (tables_dir / "source_comparison.tex").write_text(
        source_comparison_table(payload),
        encoding="utf-8",
    )
    (tables_dir / "source_quality_scores.tex").write_text(
        source_quality_scores_table(payload),
        encoding="utf-8",
    )
    (tables_dir / "visual_quality_scores.tex").write_text(
        visual_quality_scores_table(payload),
        encoding="utf-8",
    )
    (tables_dir / "visual_score_components.tex").write_text(
        visual_score_components_table(payload),
        encoding="utf-8",
    )
    (tables_dir / "visual_coverage_heatmap.tex").write_text(
        visual_coverage_heatmap_table(payload),
        encoding="utf-8",
    )
    (tables_dir / "visual_anomaly_profile.tex").write_text(
        visual_anomaly_profile_table(payload),
        encoding="utf-8",
    )
    (tables_dir / "improvement_actions.tex").write_text(
        improvement_actions_table(payload),
        encoding="utf-8",
    )
    (tables_dir / "field_coverage.tex").write_text(
        field_coverage_table(payload),
        encoding="utf-8",
    )
    for source in payload["sources"]:
        slug = source_slug(source["source"])
        (tables_dir / f"{slug}_detail.tex").write_text(
            source_detail_section(source),
            encoding="utf-8",
        )
        (tables_dir / f"{slug}_field_coverage.tex").write_text(
            source_field_coverage_table(source),
            encoding="utf-8",
        )


def metric_definitions_table(payload: dict[str, Any]) -> str:
    target_hours = payload["sources"][0]["summary"].get("refresh_target_hours", 48.0)
    definitions = [
        (
            "Completeness",
            "100 * present relevant field values / expected relevant field values",
            "Average coverage over all profiled fields.",
        ),
        (
            "Critical completeness",
            "100 * present critical field values / expected critical field values",
            "Coverage of fields required for matching and analysis.",
        ),
        (
            "Validity",
            "100 * valid present values / present values checked by validators",
            "Source-specific format checks; missingness is handled separately.",
        ),
        (
            "Spatial readiness",
            "100 * records with valid latitude/longitude pair / records",
            "Readiness for geospatial integration.",
        ),
        (
            "Timeliness",
            "max(0, 100 * (1 - collection_duration_hours / refresh_target_hours))",
            f"Refreshability against the current {fmt_float(target_hours)}h target.",
        ),
        (
            "Reliability",
            "100 * records with review_count >= low_review_threshold / records",
            "Share of ratings supported by enough reviews.",
        ),
        (
            "Uniqueness",
            "100 - 100 * duplicate flags / records",
            "Penalizes duplicate identifiers and normalized name/address keys.",
        ),
        (
            "Quality flags",
            "flags_per_100 = 100 * generated warnings / records",
            "Record-level warnings for cleaning, not a deletion list.",
        ),
    ]
    rows = [
        r"{\scriptsize",
        r"\begin{tabular}{p{0.21\linewidth}p{0.37\linewidth}p{0.32\linewidth}}",
        r"\toprule",
        r"Metric & Formula / definition & Reading \\",
        r"\midrule",
    ]
    for metric, formula, reading in definitions:
        rows.append(
            "{metric} & {formula} & {reading} \\\\".format(
                metric=latex_escape(metric),
                formula=latex_escape(formula),
                reading=latex_escape(reading),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}", r"}", ""])
    return "\n".join(rows)


def source_summary_table(payload: dict[str, Any]) -> str:
    rows = [
        r"{\tiny",
        r"\begin{tabular}{lrrrrrrrrr}",
        r"\toprule",
        (
            r"Source & Records & Score & Complete & Critical & Validity & Spatial & "
            r"Timeliness & Reliable & Flags/100 \\"
        ),
        r"\midrule",
    ]
    for source in payload["sources"]:
        summary = source["summary"]
        rows.append(
            "{source} & {records} & {score} & {complete} & {critical} & "
            "{validity} & {spatial} & {timeliness} & {reliable} & {flags} \\\\".format(
                source=latex_escape(source["source"]),
                records=source["record_count"],
                score=latex_pct(summary["overall_quality_score_pct"]),
                complete=latex_pct(summary["completeness_score_pct"]),
                critical=latex_pct(summary["critical_completeness_score_pct"]),
                validity=latex_pct(summary["validity_score_pct"]),
                spatial=latex_pct(summary["spatial_readiness_score_pct"]),
                timeliness=latex_pct(summary["timeliness_score_pct"]),
                reliable=latex_pct(summary["reliability_score_pct"]),
                flags=f"{anomaly_flags_per_100(source):.1f}",
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}", r"}", ""])
    return "\n".join(rows)


def source_quality_scores_table(payload: dict[str, Any]) -> str:
    rows = [
        r"{\tiny",
        r"\begin{tabular}{lrrrrrrr}",
        r"\toprule",
        (
            r"Source & Score & Critical & Validity & Spatial & "
            r"Uniqueness & Timeliness & Reliability \\"
        ),
        r"\midrule",
    ]
    for source in payload["sources"]:
        summary = source["summary"]
        rows.append(
            "{source} & {score} & {critical} & {validity} & {spatial} & "
            "{unique} & {time} & {reliable} \\\\".format(
                source=latex_escape(source["source"]),
                score=latex_pct(summary["overall_quality_score_pct"]),
                critical=latex_pct(summary["critical_completeness_score_pct"]),
                validity=latex_pct(summary["validity_score_pct"]),
                spatial=latex_pct(summary["spatial_readiness_score_pct"]),
                unique=latex_pct(summary["uniqueness_score_pct"]),
                time=latex_pct(summary["timeliness_score_pct"]),
                reliable=latex_pct(summary["reliability_score_pct"]),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}", r"}", ""])
    return "\n".join(rows)


def visual_quality_scores_table(payload: dict[str, Any]) -> str:
    rows = [
        r"{\small",
        r"\begin{tabular}{lrp{0.55\linewidth}}",
        r"\toprule",
        r"Source & Score & Visual scale \\",
        r"\midrule",
    ]
    for source in payload["sources"]:
        score = source["summary"]["overall_quality_score_pct"]
        rows.append(
            "{source} & {score} & {bar} \\\\".format(
                source=latex_escape(source["source"]),
                score=latex_pct(score),
                bar=latex_bar(score, "qualityblue"),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}", r"}", ""])
    return "\n".join(rows)


def visual_score_components_table(payload: dict[str, Any]) -> str:
    components = [
        ("Critical", "critical_completeness_score_pct"),
        ("Validity", "validity_score_pct"),
        ("Spatial", "spatial_readiness_score_pct"),
        ("Uniqueness", "uniqueness_score_pct"),
        ("Timeliness", "timeliness_score_pct"),
        ("Reliability", "reliability_score_pct"),
    ]
    rows = [
        r"{\scriptsize",
        r"\begin{tabular}{llrp{0.36\linewidth}}",
        r"\toprule",
        r"Source & Component & Value & Visual scale \\",
        r"\midrule",
    ]
    for source in payload["sources"]:
        summary = source["summary"]
        for label, key in components:
            value = summary[key]
            rows.append(
                "{source} & {label} & {value} & {bar} \\\\".format(
                    source=latex_escape(source["source"]),
                    label=latex_escape(label),
                    value=latex_pct(value),
                    bar=latex_bar(value, component_color(value), max_width_mm=48),
                )
            )
    rows.extend([r"\bottomrule", r"\end{tabular}", r"}", ""])
    return "\n".join(rows)


def visual_coverage_heatmap_table(payload: dict[str, Any]) -> str:
    columns = [
        ("Identifier", coverage_value_for_identity),
        ("Name", lambda source: field_coverage_pct(source, ("name", "restaurant_name"))),
        ("Address", lambda source: field_coverage_pct(source, ("address",))),
        ("Rating", lambda source: field_coverage_pct(source, ("rating",))),
        ("Reviews", lambda source: field_coverage_pct(source, ("review_count",))),
        ("Coords", lambda source: source["summary"]["valid_coordinate_pair_pct"]),
        ("Timestamp", lambda source: source["summary"]["timeliness_score_pct"]),
    ]
    rows = [
        r"{\scriptsize",
        r"\begin{tabular}{lrrrrrrr}",
        r"\toprule",
        r"Source & ID & Name & Address & Rating & Reviews & Coords & Timestamp \\",
        r"\midrule",
    ]
    for source in payload["sources"]:
        cells = [heatmap_cell(getter(source)) for _, getter in columns]
        rows.append(
            "{source} & {cells} \\\\".format(
                source=latex_escape(source["source"]),
                cells=" & ".join(cells),
            )
        )
    rows.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"}",
            "",
            r"{\footnotesize Colored markers indicate pre-integration readiness bands.}",
            "",
        ]
    )
    return "\n".join(rows)


def visual_anomaly_profile_table(payload: dict[str, Any]) -> str:
    counts = [
        (source, issue_type, count)
        for source in payload["sources"]
        for issue_type, count in anomaly_type_counts(source, limit=4)
    ]
    max_count = max((count for _, _, count in counts), default=1)
    rows = [
        r"{\scriptsize",
        r"\begin{tabular}{llrp{0.38\linewidth}}",
        r"\toprule",
        r"Source & Issue type & Count & Visual scale \\",
        r"\midrule",
    ]
    for source, issue_type, count in counts:
        rows.append(
            "{source} & {issue} & {count} & {bar} \\\\".format(
                source=latex_escape(source["source"]),
                issue=latex_escape(issue_type),
                count=count,
                bar=latex_bar((count / max_count) * 100, "qualityorange", max_width_mm=50),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}", r"}", ""])
    return "\n".join(rows)


def improvement_actions_table(payload: dict[str, Any]) -> str:
    rows = [
        r"{\scriptsize",
        r"\begin{tabular}{rp{0.18\linewidth}p{0.34\linewidth}p{0.28\linewidth}}",
        r"\toprule",
        r"Priority & Scope & Action & Expected effect \\",
        r"\midrule",
    ]
    for priority, scope, action, effect in improvement_actions(payload):
        rows.append(
            "{priority} & {scope} & {action} & {effect} \\\\".format(
                priority=priority,
                scope=latex_escape(scope),
                action=latex_escape(action),
                effect=latex_escape(effect),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}", r"}", ""])
    return "\n".join(rows)


def source_comparison_table(payload: dict[str, Any]) -> str:
    sources = payload["sources"]
    largest = max(sources, key=lambda source: source["record_count"])
    best_quality = max(
        sources,
        key=lambda source: source["summary"]["overall_quality_score_pct"],
    )
    weakest_quality = min(
        sources,
        key=lambda source: source["summary"]["overall_quality_score_pct"],
    )
    best_completeness = max(
        sources,
        key=lambda source: source["summary"]["completeness_score_pct"],
    )
    weakest_completeness = min(
        sources,
        key=lambda source: source["summary"]["completeness_score_pct"],
    )
    best_critical = max(
        sources,
        key=lambda source: source["summary"]["critical_completeness_score_pct"],
    )
    sparsest = max(
        sources,
        key=lambda source: source["summary"]["low_review_pct_of_valid_reviews"],
    )
    most_flags = max(sources, key=anomaly_flags_per_100)
    weakest_timeliness = min(
        sources,
        key=lambda source: source["summary"]["timeliness_score_pct"],
    )
    coordinate_ready = [
        source["source"]
        for source in sources
        if source["summary"]["valid_coordinate_pair_pct"] >= 95
    ]
    findings = [
        (
            "Largest source",
            f"{largest['source']} with {largest['record_count']} records.",
        ),
        (
            "Highest weighted quality score",
            f"{best_quality['source']} "
            f"({fmt_pct(best_quality['summary']['overall_quality_score_pct'])}).",
        ),
        (
            "Lowest weighted quality score",
            f"{weakest_quality['source']} "
            f"({fmt_pct(weakest_quality['summary']['overall_quality_score_pct'])}).",
        ),
        (
            "Highest completeness",
            f"{best_completeness['source']} "
            f"({fmt_pct(best_completeness['summary']['completeness_score_pct'])}).",
        ),
        (
            "Weakest completeness",
            f"{weakest_completeness['source']} "
            f"({fmt_pct(weakest_completeness['summary']['completeness_score_pct'])}).",
        ),
        (
            "Highest critical completeness",
            f"{best_critical['source']} "
            f"({fmt_pct(best_critical['summary']['critical_completeness_score_pct'])}).",
        ),
        (
            "Coordinate-ready sources",
            ", ".join(coordinate_ready)
            + "; Tripadvisor still requires latitude/longitude enrichment.",
        ),
        (
            "Tripadvisor raw limitation",
            "Lower raw score is expected: no coordinates, no record-level timestamps, "
            "and many zero/low-review records before cleaning.",
        ),
        (
            "Most sparse review evidence",
            f"{sparsest['source']} "
            f"({fmt_pct(sparsest['summary']['low_review_pct_of_valid_reviews'])}).",
        ),
        (
            "Highest quality-flag density",
            f"{most_flags['source']} "
            f"({fmt_float(anomaly_flags_per_100(most_flags))} flags per 100 records).",
        ),
        (
            "Weakest source refreshability",
            f"{weakest_timeliness['source']} "
            f"({fmt_pct(weakest_timeliness['summary']['timeliness_score_pct'])}).",
        ),
    ]
    rows = [
        r"{\small",
        r"\begin{tabular}{p{0.34\linewidth}p{0.56\linewidth}}",
        r"\toprule",
        r"Comparison & Finding \\",
        r"\midrule",
    ]
    for label, finding in findings:
        rows.append(f"{latex_escape(label)} & {latex_escape(finding)} \\\\")
    rows.extend([r"\bottomrule", r"\end{tabular}", r"}", ""])
    return "\n".join(rows)


def source_detail_section(source: dict[str, Any]) -> str:
    summary = source["summary"]
    rows = [
        rf"\subsection{{{latex_escape(source['source'])}}}",
        "",
        latex_escape(source_role(source["source"])),
        "",
        r"\paragraph{Key metrics}",
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"Metric & Value \\",
        r"\midrule",
        f"Records assessed & {source['record_count']} \\\\",
        f"Overall quality score & {latex_pct(summary['overall_quality_score_pct'])} \\\\",
        f"Average field completeness & {latex_pct(summary['completeness_score_pct'])} \\\\",
        (
            "Critical-field completeness & "
            f"{latex_pct(summary['critical_completeness_score_pct'])} \\\\"
        ),
        f"Validity score & {latex_pct(summary['validity_score_pct'])} \\\\",
        f"Uniqueness score & {latex_pct(summary['uniqueness_score_pct'])} \\\\",
        f"Timeliness score & {latex_pct(summary['timeliness_score_pct'])} \\\\",
        (
            "Collection duration & "
            f"{latex_escape(fmt_hours(summary['collection_duration_hours']))} \\\\"
        ),
        f"Timestamp coverage & {latex_pct(summary['timestamp_coverage_pct'])} \\\\",
        f"Reliability score & {latex_pct(summary['reliability_score_pct'])} \\\\",
        (
            "Format values checked & "
            f"{summary['format_valid_value_count']} / "
            f"{summary['format_checked_value_count']} valid \\\\"
        ),
        f"Native rating average & {latex_optional(summary['rating_avg'])} \\\\",
        f"Comparable rating average 0--5 & {latex_optional(comparable_rating_avg(source))} \\\\",
        (
            "Valid review counts & "
            f"{summary['valid_review_count']} "
            f"({latex_pct(summary['valid_review_count_pct'])}) \\\\"
        ),
        (
            "Low-review records & "
            f"{summary['low_review_records']} "
            f"({latex_pct(summary['low_review_pct_of_valid_reviews'])}) \\\\"
        ),
        (
            "Valid coordinate pairs & "
            f"{summary['valid_coordinate_pair_count']} "
            f"({latex_pct(summary['valid_coordinate_pair_pct'])}) \\\\"
        ),
        (
            "Latest source timestamp & "
            f"{latex_escape(fmt_optional_text(summary['latest_timestamp']))} \\\\"
        ),
        f"Data age in days & {latex_optional(summary['data_age_days'])} \\\\",
        (
            "Quality flags & "
            f"{summary['anomaly_count']} "
            f"({anomaly_flags_per_100(source):.1f} per 100 records) \\\\"
        ),
        r"\bottomrule",
        r"\end{tabular}",
        "",
        r"\paragraph{Weakest field coverage}",
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Field & Present & Missing & Coverage \\",
        r"\midrule",
    ]
    for item in lowest_coverage_fields(source, limit=7):
        rows.append(
            "{field} & {present} & {missing} & {coverage} \\\\".format(
                field=latex_escape(item["field"]),
                present=item["present"],
                missing=item["missing"],
                coverage=latex_pct(item["coverage_pct"]),
            )
        )
    rows.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            "",
            r"\paragraph{Most frequent quality flags}",
            r"\begin{tabular}{lr}",
            r"\toprule",
            r"Issue type & Count \\",
            r"\midrule",
        ]
    )
    issue_counts = anomaly_type_counts(source, limit=6)
    if issue_counts:
        for issue_type, count in issue_counts:
            rows.append(f"{latex_escape(issue_type)} & {count} \\\\")
    else:
        rows.append(r"None & 0 \\")
    rows.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            "",
            r"\paragraph{Interpretation}",
            r"\begin{itemize}",
        ]
    )
    for note in interpretation_notes(source):
        rows.append(rf"\item {latex_escape(note)}")
    rows.extend([r"\end{itemize}", ""])
    return "\n".join(rows)


def field_coverage_table(payload: dict[str, Any]) -> str:
    rows = [
        r"{\small",
        r"\begin{longtable}{llrrr}",
        r"\toprule",
        r"Source & Field & Present & Missing & Coverage \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"Source & Field & Present & Missing & Coverage \\",
        r"\midrule",
        r"\endhead",
    ]
    for source in payload["sources"]:
        for item in source["field_coverage"]:
            rows.append(
                "{source} & {field} & {present} & {missing} & {coverage} \\\\".format(
                    source=latex_escape(source["source"]),
                    field=latex_escape(item["field"]),
                    present=item["present"],
                    missing=item["missing"],
                    coverage=latex_pct(item["coverage_pct"]),
                )
            )
    rows.extend([r"\bottomrule", r"\end{longtable}", r"}", ""])
    return "\n".join(rows)


def source_field_coverage_table(source: dict[str, Any]) -> str:
    rows = [
        rf"\subsection{{{latex_escape(source['source'])}}}",
        r"{\small",
        r"\begin{longtable}{lrrr}",
        r"\toprule",
        r"Field & Present & Missing & Coverage \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"Field & Present & Missing & Coverage \\",
        r"\midrule",
        r"\endhead",
    ]
    for item in source["field_coverage"]:
        rows.append(
            "{field} & {present} & {missing} & {coverage} \\\\".format(
                field=latex_escape(item["field"]),
                present=item["present"],
                missing=item["missing"],
                coverage=latex_pct(item["coverage_pct"]),
            )
        )
    rows.extend([r"\bottomrule", r"\end{longtable}", r"}", ""])
    return "\n".join(rows)


def source_role(source_name: str) -> str:
    if source_name == "Google Places":
        return (
            "Google Places is treated as the broad geographic seed and reference source. "
            "Its coordinate coverage makes it the most useful starting point for spatial "
            "integration, while weak optional fields mostly affect enrichment depth."
        )
    if source_name == "Tripadvisor":
        return (
            "Tripadvisor contributes broad review and category information, but the raw "
            "file does not yet contain latitude and longitude or record-level timestamps. "
            "Its lower raw score is expected and should be improved through the planned "
            "cleaning and geocoding enrichment before reliable geospatial integration."
        )
    if source_name == "TheFork":
        return (
            "TheFork is the smallest source but is highly restaurant-specific and already "
            "contains near-complete coordinates. Its ratings use a native 0-10 scale, so "
            "comparison with Google and Tripadvisor requires scale normalization."
        )
    return "This source is profiled with the common quality-assessment framework."


def interpretation_notes(source: dict[str, Any]) -> list[str]:
    summary = source["summary"]
    lowest_fields = lowest_coverage_fields(source, limit=3)
    lowest_text = ", ".join(
        f"{item['field']} ({fmt_pct(item['coverage_pct'])})" for item in lowest_fields
    )
    invalid_formats = summary["format_invalid_value_count"]
    notes = [
        f"The weighted source quality score is {fmt_pct(summary['overall_quality_score_pct'])}; "
        "the score is driven by integration-critical fields rather than optional metadata.",
        f"The weakest fields are {lowest_text}; downstream logic should avoid treating "
        "them as mandatory matching keys.",
        f"Format validity checks {summary['format_checked_value_count']} present values; "
        f"{invalid_formats} fail the expected source-specific format.",
        f"The sparse-review threshold flags {summary['low_review_records']} records, "
        "so rating comparisons should account for review-count reliability.",
        f"Timeliness score is {fmt_pct(summary['timeliness_score_pct'])}, based on "
        f"collection duration {fmt_hours(summary['collection_duration_hours'])} against "
        f"a {fmt_hours(summary['refresh_target_hours'])} refresh target; timestamp "
        f"coverage is {fmt_pct(summary['timestamp_coverage_pct'])}.",
        f"The source has {summary['anomaly_count']} generated quality flags, equal to "
        f"{fmt_float(anomaly_flags_per_100(source))} flags per 100 records.",
    ]
    if source["source"] == "Google Places":
        notes.append(
            "Because valid coordinates are complete, Google can anchor the first "
            "geospatial join and help detect out-of-area records in other sources."
        )
    elif source["source"] == "Tripadvisor":
        notes.append(
            "The 0% coordinate validity is expected at this stage and should be resolved "
            "by the latitude/longitude enrichment task before integration."
        )
        notes.append(
            "The missing record-level timestamps do not force timeliness to 0 anymore; "
            "Tripadvisor refreshability is estimated from the scraper runtime instead."
        )
    elif source["source"] == "TheFork":
        notes.append(
            "TheFork is suitable for geospatial matching now, but its missing contact "
            "fields limit its usefulness for website or phone-based validation."
        )
    return notes


def improvement_actions(payload: dict[str, Any]) -> list[tuple[int, str, str, str]]:
    sources_by_name = {source["source"]: source for source in payload["sources"]}
    actions: list[tuple[int, str, str, str]] = []
    tripadvisor = sources_by_name.get("Tripadvisor")
    if tripadvisor and tripadvisor["summary"]["spatial_readiness_score_pct"] < 95:
        actions.append(
            (
                1,
                "Tripadvisor",
                "Geocode addresses or match records to Google Places before spatial joins.",
                "Raises spatial readiness and enables automated integration-error checks.",
            )
        )
    for source in payload["sources"]:
        summary = source["summary"]
        if summary["timeliness_score_pct"] < 95:
            actions.append(
                (
                    2,
                    source["source"],
                    "Document and reduce collection duration, or add incremental refresh.",
                    "Improves source refreshability when frequent updates are required.",
                )
            )
        if summary["timestamp_coverage_pct"] < 95:
            actions.append(
                (
                    2,
                    source["source"],
                    "Persist record-level scrape/acquisition timestamps and parse them in QA.",
                    "Keeps traceability separate from the refreshability score.",
                )
            )
        if summary["reliability_score_pct"] < 80:
            actions.append(
                (
                    3,
                    source["source"],
                    "Use review-count weighted ratings for cross-platform comparisons.",
                    "Reduces the impact of sparse ratings on consistency analysis.",
                )
            )
        if summary["possible_duplicate_name_address_count"] > 0:
            actions.append(
                (
                    4,
                    source["source"],
                    "Inspect duplicate normalized name/address keys before integration.",
                    "Prevents false entity matches and duplicated restaurants.",
                )
            )
    if not actions:
        actions.append(
            (
                1,
                "All sources",
                "Keep current validation gates and rerun QA after each acquisition update.",
                "Maintains reproducibility and catches source drift early.",
            )
        )
    return sorted(actions, key=lambda item: (item[0], item[1]))


def latex_bar(value: float, color: str, max_width_mm: int = 70) -> str:
    width = max(0.6, (max(0.0, min(value, 100.0)) / 100.0) * max_width_mm)
    return rf"\textcolor{{{color}}}{{\rule{{{width:.1f}mm}}{{5pt}}}}"


def component_color(value: float) -> str:
    if value >= 95:
        return "qualitygreen"
    if value >= 80:
        return "qualityblue"
    if value >= 50:
        return "qualityorange"
    return "qualityred"


def heatmap_cell(value: float) -> str:
    color = component_color(value)
    marker = rf"\textcolor{{{color}}}{{\rule{{2.5mm}}{{4pt}}}}"
    return rf"{marker} {latex_pct(value)}"


def coverage_value_for_identity(source: dict[str, Any]) -> float:
    return field_coverage_pct(source, ("place_id", "source_url", "source_id"))


def field_coverage_pct(source: dict[str, Any], field_names: tuple[str, ...]) -> float:
    for item in source["field_coverage"]:
        if item["field"] in field_names:
            return item["coverage_pct"]
    return 0.0


def lowest_coverage_fields(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    return sorted(
        source["field_coverage"],
        key=lambda item: (item["coverage_pct"], item["field"]),
    )[:limit]


def anomaly_type_counts(source: dict[str, Any], limit: int) -> list[tuple[str, int]]:
    counts = Counter(item["issue_type"] for item in source["anomalies"])
    return counts.most_common(limit)


def anomaly_flags_per_100(source: dict[str, Any]) -> float:
    if not source["record_count"]:
        return 0.0
    return (source["summary"]["anomaly_count"] / source["record_count"]) * 100


def comparable_rating_avg(source: dict[str, Any]) -> float | None:
    rating_avg = source["summary"]["rating_avg"]
    if rating_avg is None:
        return None
    rating_scale = source["summary"]["rating_scale"]
    if rating_scale == 5.0:
        return rating_avg
    if rating_scale == 10.0:
        return round(rating_avg / 2, 3)
    return round((rating_avg / rating_scale) * 5, 3)


def sparse_review_text(source: dict[str, Any]) -> str:
    summary = source["summary"]
    return (
        f"{summary['low_review_records']} "
        f"({fmt_pct(summary['low_review_pct_of_valid_reviews'])})"
    )


def source_slug(source_name: str) -> str:
    return source_name.lower().replace(" ", "_").replace("-", "_").replace("/", "_")


def fmt_optional(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return fmt_float(value)
    return str(value)


def fmt_optional_text(value: Any) -> str:
    return "n/a" if value is None else str(value)


def fmt_hours(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2f} h"


def fmt_float(value: float) -> str:
    return f"{value:.2f}"


def fmt_pct(value: float) -> str:
    return f"{value:.2f}%"


def latex_optional(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def latex_pct(value: float) -> str:
    return f"{value:.2f}\\%"


def latex_escape(value: Any) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)
