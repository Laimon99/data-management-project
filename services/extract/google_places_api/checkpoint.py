import json
from pathlib import Path

from .tiling import Tile


class TileCheckpoint:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._done: set[tuple[float, float, int]] = set()
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._done = {tuple(item) for item in data.get("done", [])}

    @staticmethod
    def _key(tile: Tile) -> tuple[float, float, int]:
        return (round(tile.lat, 6), round(tile.lon, 6), int(tile.radius_m))

    def has(self, tile: Tile) -> bool:
        return self._key(tile) in self._done

    def add(self, tile: Tile) -> None:
        self._done.add(self._key(tile))
        self._save()

    def _save(self) -> None:
        payload = {"done": [list(k) for k in sorted(self._done)]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)


class DetailCheckpoint:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._done: set[str] = set()
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as f:
                for raw in f:
                    pid = raw.strip()
                    if pid:
                        self._done.add(pid)

    def has(self, place_id: str) -> bool:
        return place_id in self._done

    def add(self, place_id: str) -> None:
        if place_id in self._done:
            return
        self._done.add(place_id)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(place_id + "\n")
