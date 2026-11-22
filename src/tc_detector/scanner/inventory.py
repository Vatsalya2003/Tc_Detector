"""The scan's output: which services a repo has and which files rules should read.

Paths are "/"-separated. A service's `root` is relative to the scanned folder ("." if the
scanned folder is itself the service). Its files are relative to its own root, like a
candidate's `file`. `repo_files` are files in no service, relative to the scanned folder.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tc_detector.scanner.groups import GROUPS, empty_groups


@dataclass
class Service:
    name: str  # e.g. "customers-service"; what candidates and labels write in `service`
    root: str  # e.g. "spring-petclinic-customers-service"
    name_source: str  # "spring.application.name" or "folder"
    files: dict[str, list[str]] = field(default_factory=empty_groups)

    def contains(self, path: str) -> bool:
        """Is `path` (relative to the scanned folder) inside this service's folder?"""
        return self.root == "." or path == self.root or path.startswith(self.root + "/")


@dataclass
class Inventory:
    repo: str
    commit: str
    services: list[Service] = field(default_factory=list)
    repo_files: list[str] = field(default_factory=list)

    def service_for(self, path: str) -> Service | None:
        """The service a file belongs to: the deepest one whose folder holds it.

        `path` is relative to the scanned folder. None means the file is in no service.
        """
        holders = [s for s in self.services if s.contains(path)]
        return max(holders, key=lambda s: len(Path(s.root).parts), default=None)

    def service_root(self, name: str) -> str:
        """The folder of the service called `name`. Raises KeyError for an unknown name."""
        for s in self.services:
            if s.name == name:
                return s.root
        raise KeyError(f"no service named {name!r}")

    def file_count(self) -> int:
        """Every file listed: grouped service files plus repo_files."""
        grouped = sum(len(files) for s in self.services for files in s.files.values())
        return grouped + len(self.repo_files)

    # ---------------------------------------------------------------- JSON

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Inventory:
        """Read an inventory back. Raises ValueError if a key or file group is missing."""
        data: dict[str, Any] = json.loads(text)
        try:
            services = [
                Service(s["name"], s["root"], s["name_source"], {g: s["files"][g] for g in GROUPS})
                for s in data["services"]
            ]
            return cls(data["repo"], data["commit"], services, data["repo_files"])
        except (KeyError, TypeError) as e:
            raise ValueError(f"not a valid inventory: missing {e}") from None

    def save(self, path: Path) -> None:
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Inventory:
        return cls.from_json(path.read_text(encoding="utf-8"))
