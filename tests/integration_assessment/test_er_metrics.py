from integration_assessment.er_metrics import compute_er_metrics, cross_validate_thresholds


def _gold(candidate_id, human_label, source="tripadvisor", score="0.9", is_chain="False"):
    return {
        "_id": candidate_id,
        "source": source,
        "google_id": f"g-{candidate_id}",
        "source_id": f"s-{candidate_id}",
        "score": score,
        "is_chain": is_chain,
        "human_label": human_label,
    }


def _candidate(candidate_id, predicted, source="tripadvisor", score=0.9, is_chain=False):
    return {
        "_id": candidate_id,
        "source": source,
        "google_id": f"g-{candidate_id}",
        "source_id": f"s-{candidate_id}",
        "label": predicted,
        "llm_label": None,
        "score": score,
        "dmin": 0.4,
        "dmax": 0.8,
        "is_chain": is_chain,
    }


def test_er_confusion_precision_recall_and_breakdowns():
    gold = [
        _gold("c1", "MATCH", score="0.95"),
        _gold("c2", "MATCH", score="0.2"),
        _gold("c3", "NON_MATCH", source="thefork", score="0.6", is_chain="True"),
        _gold("c4", "NON_MATCH", score="0.1"),
    ]
    candidates = [
        _candidate("c1", "MATCH", score=0.95),
        _candidate("c2", "NON_MATCH", score=0.2),
        _candidate("c3", "UNCERTAIN", source="thefork", score=0.6, is_chain=True),
        _candidate("c4", "NON_MATCH", score=0.1),
    ]

    metrics = compute_er_metrics(gold, candidates)
    overall = metrics["in_sample"]["summaries"]["overall:all"]

    assert overall["matrix"]["MATCH"]["MATCH"] == 1
    assert overall["matrix"]["MATCH"]["NON_MATCH"] == 1
    assert overall["matrix"]["NON_MATCH"]["UNCERTAIN"] == 1
    assert overall["match_precision"] == 1.0
    assert overall["match_recall_strict"] == 0.5
    assert overall["match_recall_kept"] == 0.5
    assert overall["accuracy"] == 0.5
    assert overall["uncertain_rate"] == 0.25
    assert "source:thefork" in metrics["in_sample"]["summaries"]
    assert "chain:chain" in metrics["in_sample"]["summaries"]


def test_cross_validation_returns_finite_fold_stats():
    gold = [_gold(f"m{i}", "MATCH", score="0.95") for i in range(5)] + [
        _gold(f"n{i}", "NON_MATCH", source="thefork", score="0.1") for i in range(5)
    ]

    cv = cross_validate_thresholds(gold, folds=5, seed=7)

    assert len(cv["overall"]["folds"]) == 5
    assert cv["overall"]["summary"]["match_precision"]["mean"] is not None
    assert cv["overall"]["summary"]["uncertain_rate"]["mean"] is not None
