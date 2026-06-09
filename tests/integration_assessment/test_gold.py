import csv

from integration_assessment.gold import load_gold_rows


def _write_csv(path, rows):
    fieldnames = ["_id", "source", "google_id", "source_id", "score", "is_chain", "human_label"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_gold_loader_dedupes_by_candidate_id_with_latest_file_winning(tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    _write_csv(
        first,
        [
            {
                "_id": "c1",
                "source": "tripadvisor",
                "google_id": "g1",
                "source_id": "ta1",
                "score": "0.9",
                "is_chain": "False",
                "human_label": "MATCH",
            }
        ],
    )
    _write_csv(
        second,
        [
            {
                "_id": "c1",
                "source": "tripadvisor",
                "google_id": "g1",
                "source_id": "ta1",
                "score": "0.9",
                "is_chain": "False",
                "human_label": "NON_MATCH",
            },
            {
                "_id": "c2",
                "source": "thefork",
                "google_id": "g2",
                "source_id": "tf1",
                "score": "0.1",
                "is_chain": "True",
                "human_label": "",
            },
        ],
    )

    rows = load_gold_rows([first, second])

    assert len(rows) == 1
    assert rows[0]["_id"] == "c1"
    assert rows[0]["human_label"] == "NON_MATCH"
    assert rows[0]["gold_path"] == str(second)
