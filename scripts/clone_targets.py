"""Clone every repo in targets.yaml into targets/<name>, at its pinned commit.

Run from anywhere:  uv run python scripts/clone_targets.py

- New repo: clones it, then checks out the pinned commit.
- Existing folder: fetches, then checks out the pinned commit (no re-clone).
- Entries whose url or commit starts with TODO are skipped.
- After checkout, HEAD must equal the pinned commit, or the script exits with an error.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGETS_FILE = ROOT / "targets.yaml"
TARGETS_DIR = ROOT / "targets"


class CloneError(Exception):
    """A repo could not be put at its pinned commit."""


def git(*args: str, cwd: Path | None = None) -> str:
    """Run one git command and return its output; raise CloneError if it fails."""
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise CloneError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def is_todo(value: str) -> bool:
    """True if a url/commit is still a placeholder like TODO or TODO-pin-sha."""
    return value.strip().upper().startswith("TODO")


def has_commit(repo: Path, commit: str) -> bool:
    """True if the commit is already present in the local clone."""
    check = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=repo, capture_output=True
    )
    return check.returncode == 0


def sync(name: str, url: str, commit: str) -> None:
    """Clone or update one repo and check out its pinned commit."""
    dest = TARGETS_DIR / name
    if dest.exists():
        if not (dest / ".git").exists():
            raise CloneError(f"{dest} exists but is not a git repo; move it away and rerun")
        origin = git("remote", "get-url", "origin", cwd=dest)
        if origin.removesuffix(".git") != url.removesuffix(".git"):
            raise CloneError(f"{dest} points at {origin}, but targets.yaml says {url}")
        # Local edits would make the scan differ from the pinned commit.
        if git("status", "--porcelain", cwd=dest):
            raise CloneError(f"{dest} has local changes; commit, stash or discard them first")
        print(f"[{name}] exists, fetching")
        git("fetch", "--quiet", "origin", cwd=dest)
    else:
        print(f"[{name}] cloning {url}")
        TARGETS_DIR.mkdir(exist_ok=True)
        git("clone", "--quiet", url, str(dest))

    # A pinned commit may no longer be on any branch; fetch it by SHA if needed.
    if not has_commit(dest, commit):
        git("fetch", "--quiet", "origin", commit, cwd=dest)
    git("checkout", "--quiet", "--detach", commit, cwd=dest)

    head = git("rev-parse", "HEAD", cwd=dest)
    if head != commit:
        raise CloneError(f"{dest} HEAD is {head}, expected {commit}")
    print(f"[{name}] OK at {head}")


def main() -> int:
    data = yaml.safe_load(TARGETS_FILE.read_text(encoding="utf-8"))
    failures = []
    for target in data["targets"]:
        name = target["name"]
        url, commit = target.get("url"), target.get("commit")
        # YAML reads an all-digit SHA as a number, which loses leading zeros.
        if not isinstance(url, str) or not isinstance(commit, str):
            print(f"[{name}] FAILED: url and commit must be text; quote them", file=sys.stderr)
            failures.append(name)
            continue
        if is_todo(url) or is_todo(commit):
            print(f"[{name}] SKIPPED: url or commit is still TODO in targets.yaml")
            continue
        try:
            sync(name, url, commit)
        except CloneError as error:
            print(f"[{name}] FAILED: {error}", file=sys.stderr)
            failures.append(name)
    if failures:
        print(f"\nFAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
