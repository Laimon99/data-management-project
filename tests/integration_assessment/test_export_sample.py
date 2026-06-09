import csv
from dataclasses import dataclass

import mongomock

from integration_assessment.cli import export_unlabeled_sample
from integration_assessment.config import IntegrationAssessmentSettings


@dataclass
class _Collections:
    candidates: object
    google: object
    tripadvisor: object
    thefork: object


def test_export_sample_excludes_existing_gold_ids(tmp_path):
    db = mongomock.MongoClient()["dataman"]
    db.candidates.insert_many(
        [
            {
                "_id": "already-labeled",
                "source": "tripadvisor",
                "google_id": "g1",
                "source_id": "ta1",
                "label": "MATCH",
                "score": 0.95,
                "components": {},
            },
            {
                "_id": "new-candidate",
                "source": "tripadvisor",
                "google_id": "g2",
                "source_id": "ta2",
                "label": "UNCERTAIN",
                "score": 0.5,
                "components": {},
            },
        ]
    )
    db.google.insert_many([{"_id": "g1", "place_id": "g1"}, {"_id": "g2", "place_id": "g2"}])
    db.tripadvisor.insert_many(
        [{"_id": "ta1", "ta_location_id": "ta1"}, {"_id": "ta2", "ta_location_id": "ta2"}]
    )
    gold = tmp_path / "gold.csv"
    gold.write_text(
        "_id,source,google_id,source_id,score,is_chain,human_label\n"
        "already-labeled,tripadvisor,g1,ta1,0.95,False,MATCH\n",
        encoding="utf-8",
    )
    output = tmp_path / "expand.csv"
    collections = _Collections(db.candidates, db.google, db.tripadvisor, db.thefork)
    settings = IntegrationAssessmentSettings(_env_file=None)

    count = export_unlabeled_sample(
        collections=collections,
        settings=settings,
        output=output,
        sample_size=10,
        gold_csv=[gold],
    )

    assert count == 1
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["_id"] for row in rows] == ["new-candidate"]
