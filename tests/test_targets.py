"""Offline checks that targets.yaml is well formed (no network, no cloning)."""

import re
from pathlib import Path, PurePosixPath

import pytest
import yaml

TARGETS_FILE = Path(__file__).resolve().parents[1] / "targets.yaml"
FULL_SHA = re.compile(r"[0-9a-f]{40}")
REQUIRED = ("name", "url", "commit", "role")


def load_targets() -> list[dict]:
    data = yaml.safe_load(TARGETS_FILE.read_text(encoding="utf-8"))
    return data["targets"]


TARGETS = load_targets()


def test_targets_file_loads():
    assert isinstance(TARGETS, list)
    assert TARGETS, "targets.yaml lists no targets"


@pytest.mark.parametrize("target", TARGETS, ids=lambda t: str(t.get("name")))
def test_every_target_has_required_fields(target):
    missing = [key for key in REQUIRED if not target.get(key)]
    assert not missing, f"missing or empty: {missing}"


@pytest.mark.parametrize("target", TARGETS, ids=lambda t: str(t.get("name")))
def test_pinned_commit_is_full_sha(target):
    commit = target["commit"]
    # YAML turns an unquoted all-digit SHA into a number; it must stay text.
    assert isinstance(commit, str), f"commit {commit!r} must be a string; quote it"
    assert FULL_SHA.fullmatch(commit), f"{commit!r} is not a full 40-character lowercase hex SHA"


def test_names_are_unique():
    names = [target["name"] for target in TARGETS]
    assert len(names) == len(set(names)), f"duplicate names: {names}"


@pytest.mark.parametrize("target", TARGETS, ids=lambda t: str(t.get("name")))
def test_subfolder_path_is_relative(target):
    """`path` is optional; when set it must be a plain subfolder inside the clone."""
    if "path" not in target:
        return
    path = target["path"]
    assert isinstance(path, str) and path.strip(), f"path {path!r} must be a non-empty string"
    parts = PurePosixPath(path).parts
    assert "\\" not in path, f"path {path!r} must use /"
    assert not PurePosixPath(path).is_absolute(), f"path {path!r} must be relative"
    assert ".." not in parts, f"path {path!r} must stay inside the repo"
