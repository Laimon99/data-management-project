import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

from .config import Settings
from .schema import SeedDoc


class SeedStore(Protocol):
    def upsert(self, doc: SeedDoc) -> None: ...
    def get(self, place_id: str) -> SeedDoc | None: ...
    def iter_place_ids(self) -> Iterator[str]: ...
    def close(self) -> None: ...


class JsonlSeedStore:
    """Document store backed by a single JSONL file.

    Crash-safety: each upsert rewrites the whole file via tmp + os.replace.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._docs: dict[str, SeedDoc] = {}
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        with self.path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                doc = SeedDoc.model_validate_json(line)
                self._docs[doc.place_id] = doc

    def _flush(self) -> None:
        fd, tmp_path = tempfile.mkstemp(
            prefix=self.path.name + ".",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for place_id in sorted(self._docs.keys()):
                    f.write(self._docs[place_id].model_dump_json())
                    f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def upsert(self, doc: SeedDoc) -> None:
        existing = self._docs.get(doc.place_id)
        if existing is not None:
            update: dict[str, Any] = {"seed_collected_at": existing.seed_collected_at}
            if doc.details is None and existing.details is not None:
                update["details"] = existing.details
                update["details_fetched_at"] = existing.details_fetched_at
            doc = doc.model_copy(update=update)
        self._docs[doc.place_id] = doc
        self._flush()

    def get(self, place_id: str) -> SeedDoc | None:
        return self._docs.get(place_id)

    def iter_place_ids(self) -> Iterator[str]:
        return iter(list(self._docs.keys()))

    def close(self) -> None:
        return None


class MongoSeedStore:
    """MongoDB-backed store. Wired but not the default backend in this PR."""

    def __init__(self, uri: str, db: str, collection: str) -> None:
        from pymongo import MongoClient

        self._client = MongoClient(uri)
        self._coll = self._client[db][collection]
        self._coll.create_index("place_id", unique=True)

    def upsert(self, doc: SeedDoc) -> None:
        payload = doc.model_dump(mode="json")
        existing = self._coll.find_one({"place_id": doc.place_id})
        if existing is None:
            self._coll.insert_one(payload)
            return
        if doc.details is None and existing.get("details") is not None:
            payload["details"] = existing["details"]
            payload["details_fetched_at"] = existing.get("details_fetched_at")
        payload["seed_collected_at"] = existing.get("seed_collected_at")
        self._coll.update_one({"place_id": doc.place_id}, {"$set": payload})

    def get(self, place_id: str) -> SeedDoc | None:
        raw = self._coll.find_one({"place_id": place_id}, {"_id": 0})
        if raw is None:
            return None
        return SeedDoc.model_validate(raw)

    def iter_place_ids(self) -> Iterator[str]:
        for raw in self._coll.find({}, {"_id": 0, "place_id": 1}):
            yield raw["place_id"]

    def close(self) -> None:
        self._client.close()


def make_store(settings: Settings) -> SeedStore:
    if settings.seed_store_backend == "mongo":
        if not settings.mongo_uri:
            raise ValueError("seed_store_backend=mongo but DATAMAN_MONGO_URI is not set")
        return MongoSeedStore(settings.mongo_uri, settings.mongo_db, settings.mongo_collection)
    return JsonlSeedStore(settings.seed_jsonl_path)
