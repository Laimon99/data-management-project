from __future__ import annotations

from pathlib import Path
from typing import Any


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _overall_er(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["er"]["in_sample"]["summaries"].get("overall:all", {})


def _calibration_er(payload: dict[str, Any]) -> dict[str, Any]:
    return (
        payload["er"]
        .get("calibration_in_sample", {})
        .get("summaries", {})
        .get(
            "overall:all",
            {},
        )
    )


def _paths_text(paths: list[str]) -> str:
    return ", ".join(f"`{path}`" for path in paths) or "none loaded"


def _calibration_link(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("link_survival_in_calibration") or {}


def _calibration_geo(payload: dict[str, Any]) -> dict[str, Any]:
    return (payload.get("geocoding_in_calibration") or {}).get("summary", {})


def write_markdown_report(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    er = _overall_er(payload)
    calibration_er = _calibration_er(payload)
    link = payload["link_survival"]
    geo = payload["geocoding"]["summary"]
    cv = payload["er"]["cross_validation"]["overall"]["summary"]
    precision_cv = cv.get("match_precision", {})
    recall_cv = cv.get("match_recall_kept", {})
    uncertain_cv = cv.get("uncertain_rate", {})
    gold = payload["gold"]

    lines = [
        "# Post-Integration Assessment",
        "",
        f"Generated at: `{payload['generated_at']}`",
        "",
        "This report measures automated entity resolution, one-to-one link selection,",
        "and Tripadvisor spatial enrichment against hand-labeled gold rows.",
        "",
        "## Gold Standard",
        "",
        "- Out-of-sample rows after CSV de-duplication: "
        f"**{gold['evaluation']['rows_after_csv_dedupe']}**.",
        f"- Out-of-sample evaluation rows used: **{gold['evaluation']['rows']}**.",
        f"- Out-of-sample files: {_paths_text(gold['evaluation']['sources'])}.",
        f"- In-calibration rows: **{gold['in_calibration']['rows']}**.",
        f"- In-calibration files: {_paths_text(gold['in_calibration']['sources'])}.",
        "- Evaluation rows excluded because they also appeared in calibration files: "
        f"**{gold['evaluation']['excluded_overlap_with_in_calibration']}**.",
        "",
        "## Entity Resolution Classifier: Out-of-Sample",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| MATCH precision | {_pct(er.get('match_precision'))} |",
        f"| Strict MATCH recall | {_pct(er.get('match_recall_strict'))} |",
        f"| MATCH-or-UNCERTAIN kept recall | {_pct(er.get('match_recall_kept'))} |",
        f"| Accuracy | {_pct(er.get('accuracy'))} |",
        f"| Uncertain rate | {_pct(er.get('uncertain_rate'))} |",
        f"| Gold rows missing from Mongo | {_fmt(er.get('missing_from_mongo'), 0)} |",
        "",
        "Five-fold cross-validation refits thresholds on the in-calibration gold rows",
        "and scores the held-out fold inside that calibration set:",
        "",
        "| CV metric | Mean | Std |",
        "|---|---:|---:|",
        (
            f"| MATCH precision | {_pct(precision_cv.get('mean'))} | "
            f"{_pct(precision_cv.get('std'))} |"
        ),
        (
            f"| MATCH-or-UNCERTAIN kept recall | {_pct(recall_cv.get('mean'))} | "
            f"{_pct(recall_cv.get('std'))} |"
        ),
        (
            f"| Uncertain rate | {_pct(uncertain_cv.get('mean'))} | "
            f"{_pct(uncertain_cv.get('std'))} |"
        ),
        "",
    ]
    if calibration_er:
        lines.extend(
            [
                "## Entity Resolution Classifier: In-Calibration",
                "",
                "| Metric | Value |",
                "|---|---:|",
                f"| MATCH precision | {_pct(calibration_er.get('match_precision'))} |",
                f"| Strict MATCH recall | {_pct(calibration_er.get('match_recall_strict'))} |",
                (
                    "| MATCH-or-UNCERTAIN kept recall | "
                    f"{_pct(calibration_er.get('match_recall_kept'))} |"
                ),
                f"| Accuracy | {_pct(calibration_er.get('accuracy'))} |",
                f"| Uncertain rate | {_pct(calibration_er.get('uncertain_rate'))} |",
                "",
            ]
        )

    lines.extend(
        [
            "## End-to-End Survival",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Human-confirmed MATCH pairs | {_fmt(link['total_true_matches'], 0)} |",
            f"| Classified as MATCH | {_fmt(link['classifier_match_true_matches'], 0)} |",
            f"| Selected links | {_fmt(link['linked_true_matches'], 0)} |",
            f"| Integrated source blocks | {_fmt(link['integrated_true_matches'], 0)} |",
            f"| Link survival rate | {_pct(link['link_survival_rate'])} |",
            f"| Integration survival rate | {_pct(link['integration_survival_rate'])} |",
            f"| Dropped by 1:1 selection | {_fmt(link['dropped_by_1to1_selection'], 0)} |",
            f"| Linked but missing source doc | {_fmt(link['missing_source_doc_count'], 0)} |",
            "",
            "## Spatial Enrichment",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Tripadvisor gold MATCH distance rows | {_fmt(geo['distance_rows'], 0)} |",
            f"| Median geocoding error | {_fmt(geo['median_m'], 1)} m |",
            f"| p90 geocoding error | {_fmt(geo['p90_m'], 1)} m |",
            f"| p95 geocoding error | {_fmt(geo['p95_m'], 1)} m |",
            f"| Max geocoding error | {_fmt(geo['max_m'], 1)} m |",
            f"| Within 50 m | {_pct(geo.get('within_50m_pct'))} |",
            f"| Within 100 m | {_pct(geo.get('within_100m_pct'))} |",
            f"| Within 250 m | {_pct(geo.get('within_250m_pct'))} |",
            (
                "| Tripadvisor coordinate coverage | "
                f"{_pct(geo['tripadvisor_coordinate_coverage_pct'])} |"
            ),
            "| Tripadvisor records without coordinates | "
            f"{_fmt(geo['tripadvisor_without_coordinates'], 0)} |",
            "| Tripadvisor UNBLOCKABLE candidates | "
            f"{_fmt(geo['tripadvisor_unblockable_candidates'], 0)} |",
            "",
            "## Generated Files",
            "",
            "- `data/quality/integration_assessment/integration_assessment_metrics.json`: "
            "full structured payload.",
            "- `data/quality/integration_assessment/integration_er_confusion.csv`: "
            "confusion matrix and breakdowns.",
            "- `data/quality/integration_assessment/integration_errors.csv`: "
            "misclassified and dropped rows.",
            "- `data/quality/integration_assessment/integration_geocoding_error.csv`: "
            "per-pair distance diagnostics.",
            "- `report/post_integration/tables/*.tex`: report-ready LaTeX tables.",
            "",
            "## Methodological Notes",
            "",
            "- Out-of-sample ER numbers use only rows passed with `--gold-csv`.",
            "- In-calibration rows passed with `--in-calibration-gold-csv` are used for",
            "  the calibration/CV block and are excluded from out-of-sample evaluation",
            "  when the same candidate `_id` appears in both roles.",
            "- Geocoding error among matches is truncated by the 150 m blocking radius.",
            "  True matches geocoded farther away usually become ER recall loss, coordinate",
            "  coverage failures, or UNBLOCKABLE candidates rather than large observed",
            "  distance rows.",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _escape_tex(value: Any) -> str:
    text = _fmt(value)
    return (
        text.replace("\\", "\\textbackslash{}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("#", "\\#")
    )


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    columns = "l" + "r" * (len(headers) - 1)
    lines = [
        "\\begin{tabular}{" + columns + "}",
        "\\toprule",
        " & ".join(_escape_tex(header) for header in headers) + " \\\\",
        "\\midrule",
    ]
    for row in rows:
        lines.append(" & ".join(_escape_tex(item) for item in row) + " \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    return "\n".join(lines)


def latex_metric_definitions() -> str:
    return "\n".join(
        [
            "\\begin{tabular}{p{0.28\\linewidth}p{0.66\\linewidth}}",
            "\\toprule",
            "Metric & Formula \\\\",
            "\\midrule",
            "MATCH precision & $P_M=TP_M/(TP_M+FP_M)$ \\\\",
            "Strict MATCH recall & $R_M=TP_M/(TP_M+FN_M)$ \\\\",
            "Kept MATCH recall & $R_K=K_M/H_M$ \\\\",
            "Accuracy & $(\\mathrm{TP}_{M}+\\mathrm{TN}_{N})/n$ \\\\",
            "Uncertain rate & $U/n$ \\\\",
            "Human MATCH pairs & $H_M$ \\\\",
            "Classified MATCH pairs & $A_M$ \\\\",
            "Selected MATCH links & $L_M$ \\\\",
            "Integrated MATCH pairs & $I_M$ \\\\",
            "Link survival & $S_L=L_M/H_M$ \\\\",
            "Integration survival & $S_I=I_M/H_M$ \\\\",
            "Dropped by 1:1 selection & $D_M$ \\\\",
            "Linked but missing source doc & $Q_M$ \\\\",
            "Geocoding error median & $\\mathrm{median}(d_i)$ \\\\",
            "Geocoding error p90 & $P_{90}(d_i)$ \\\\",
            "Geocoding error p95 & $P_{95}(d_i)$ \\\\",
            "Geocoding error max & $\\max(d_i)$ \\\\",
            (
                "Haversine term & "
                "$d_i=2R\\arctan2(\\sqrt{a_i},\\sqrt{1-a_i})$, "
                "$a=\\sin^2(\\Delta\\varphi/2)+\\cos\\varphi_g\\cos\\varphi_t"
                "\\sin^2(\\Delta\\lambda/2)$ \\\\"
            ),
            "Within 100 m & $\\#\\{d_i \\leq 100\\}/m$ \\\\",
            "Coordinate coverage & $C_T=T_{coord}/T$ \\\\",
            "\\midrule",
            (
                "Symbols & $H_M$: human MATCH pairs; $K_M$: human MATCH rows predicted "
                "MATCH or UNCERTAIN; $A_M$: human MATCH rows classified MATCH; "
                "$L_M$: linked MATCH pairs; $I_M$: integrated MATCH pairs; "
                "$D_M$: true matches classified MATCH but not selected; $Q_M$: "
                "selected links missing from integrated; $T$: Tripadvisor records. \\\\"
            ),
            "\\bottomrule",
            "\\end{tabular}",
            "",
        ]
    )


def _comparison_table(headers: list[str], rows: list[list[Any]]) -> str:
    columns = "l" + "r" * (len(headers) - 1)
    lines = [
        "\\begin{tabular}{" + columns + "}",
        "\\toprule",
        " & ".join(_escape_tex(header) for header in headers) + " \\\\",
        "\\midrule",
    ]
    for row in rows:
        lines.append(" & ".join(_escape_tex(item) for item in row) + " \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    return "\n".join(lines)


def write_latex_tables(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    er = _overall_er(payload)
    calibration_er = _calibration_er(payload)
    link = payload["link_survival"]
    calibration_link = _calibration_link(payload)
    geo = payload["geocoding"]["summary"]
    calibration_geo = _calibration_geo(payload)
    gold = payload["gold"]

    (output_dir / "gold_sample_counts.tex").write_text(
        _comparison_table(
            ["Sample group", "Rows"],
            [
                ["In-calibration rows", gold["in_calibration"]["rows"]],
                [
                    "Out-of-sample rows after CSV de-duplication",
                    gold["evaluation"]["rows_after_csv_dedupe"],
                ],
                [
                    "Out-of-sample rows removed as calibration overlap",
                    gold["evaluation"]["excluded_overlap_with_in_calibration"],
                ],
                ["Out-of-sample rows used", gold["evaluation"]["rows"]],
            ],
        ),
        encoding="utf-8",
    )

    (output_dir / "er_metrics.tex").write_text(
        _comparison_table(
            ["Metric", "Out-of-sample", "In-calibration"],
            [
                [
                    "MATCH precision",
                    _pct(er.get("match_precision")),
                    _pct(calibration_er.get("match_precision")),
                ],
                [
                    "Strict MATCH recall",
                    _pct(er.get("match_recall_strict")),
                    _pct(calibration_er.get("match_recall_strict")),
                ],
                [
                    "Kept MATCH recall",
                    _pct(er.get("match_recall_kept")),
                    _pct(calibration_er.get("match_recall_kept")),
                ],
                ["Accuracy", _pct(er.get("accuracy")), _pct(calibration_er.get("accuracy"))],
                [
                    "Uncertain rate",
                    _pct(er.get("uncertain_rate")),
                    _pct(calibration_er.get("uncertain_rate")),
                ],
            ],
        ),
        encoding="utf-8",
    )
    (output_dir / "end_to_end_survival.tex").write_text(
        _comparison_table(
            ["Metric", "Out-of-sample", "In-calibration"],
            [
                [
                    "Human MATCH pairs",
                    link["total_true_matches"],
                    calibration_link.get("total_true_matches"),
                ],
                [
                    "Classified MATCH pairs",
                    link["classifier_match_true_matches"],
                    calibration_link.get("classifier_match_true_matches"),
                ],
                [
                    "Selected MATCH links",
                    link["linked_true_matches"],
                    calibration_link.get("linked_true_matches"),
                ],
                [
                    "Integrated MATCH pairs",
                    link["integrated_true_matches"],
                    calibration_link.get("integrated_true_matches"),
                ],
                [
                    "Link survival",
                    _pct(link["link_survival_rate"]),
                    _pct(calibration_link.get("link_survival_rate")),
                ],
                [
                    "Integration survival",
                    _pct(link["integration_survival_rate"]),
                    _pct(calibration_link.get("integration_survival_rate")),
                ],
                [
                    "Dropped by 1:1 selection",
                    link["dropped_by_1to1_selection"],
                    calibration_link.get("dropped_by_1to1_selection"),
                ],
                [
                    "Linked but missing source doc",
                    link["missing_source_doc_count"],
                    calibration_link.get("missing_source_doc_count"),
                ],
            ],
        ),
        encoding="utf-8",
    )
    (output_dir / "geocoding_error.tex").write_text(
        _comparison_table(
            ["Metric", "Out-of-sample", "In-calibration"],
            [
                [
                    "Geocoding error median",
                    _fmt(geo["median_m"], 1),
                    _fmt(calibration_geo.get("median_m"), 1),
                ],
                [
                    "Geocoding error p90",
                    _fmt(geo["p90_m"], 1),
                    _fmt(calibration_geo.get("p90_m"), 1),
                ],
                [
                    "Geocoding error p95",
                    _fmt(geo["p95_m"], 1),
                    _fmt(calibration_geo.get("p95_m"), 1),
                ],
                [
                    "Geocoding error max",
                    _fmt(geo["max_m"], 1),
                    _fmt(calibration_geo.get("max_m"), 1),
                ],
                [
                    "Within 100 m",
                    _pct(geo.get("within_100m_pct")),
                    _pct(calibration_geo.get("within_100m_pct")),
                ],
                [
                    "Coordinate coverage",
                    _pct(geo["tripadvisor_coordinate_coverage_pct"]),
                    _pct(calibration_geo.get("tripadvisor_coordinate_coverage_pct")),
                ],
            ],
        ),
        encoding="utf-8",
    )
    (output_dir / "metric_definitions.tex").write_text(
        latex_metric_definitions(),
        encoding="utf-8",
    )
