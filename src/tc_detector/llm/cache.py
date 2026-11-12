"""On-disk cache of Claude answers, keyed by everything that shapes the request.

A repeat run with the same model, prompt version, effort, candidate text and
repeat index reads the answer from disk and spends no tokens (story S5).

CI points `cache_dir` at committed fixtures, so tests need no API key.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def request_key(material: dict[str, Any]) -> str:
    """Stable hash of the request. Sorted keys so dict order can't change it."""
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, cache_dir: Path | str):
        self.dir = Path(cache_dir)

    def _path(self, key: str) -> Path:
        # Two-level fan-out keeps directories small once experiments pile up.
        return self.dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    def put(self, key: str, entry: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so an interrupted run never leaves a half-written entry.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(entry, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
