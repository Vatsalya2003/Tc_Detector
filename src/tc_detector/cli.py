"""Command-line entry point: `uv run tc-detect` runs main() below.

tc-detect                     print the version (so does `tc-detect --version`)
tc-detect scan --repo PATH --out DIR [--repo-name NAME] [--commit SHA]
                              write DIR/inventory.json (stage 1)
"""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import version
from pathlib import Path

from tc_detector.scanner import scan


def _version() -> str:
    # Read the version from the installed package, so pyproject.toml stays the
    # only place it is written and the two can never disagree.
    return f"tc-detect {version('tc-detector')}"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tc-detect")
    p.add_argument("--version", action="version", version=_version())
    sub = p.add_subparsers(dest="command")
    s = sub.add_parser("scan", help="inventory a repo's services and files")
    s.add_argument("--repo", type=Path, required=True, help="folder to scan (may be a subfolder)")
    s.add_argument("--out", type=Path, required=True, help="folder for inventory.json")
    s.add_argument("--repo-name", help="the target's name in targets.yaml; default: folder name")
    s.add_argument("--commit", help="pinned SHA; default: the checkout's git HEAD")
    return p


def run_scan(args: argparse.Namespace) -> int:
    repo, out = args.repo.resolve(), args.out.resolve()
    # The scanner never writes to the target repo, so output can't go inside it.
    if out.is_relative_to(repo):
        sys.exit(f"error: --out {args.out} is inside the scanned repo; pick a folder outside it")
    try:
        inv = scan(repo, args.repo_name, args.commit)
    except ValueError as e:
        sys.exit(f"error: {e}")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "inventory.json"
    inv.save(path)
    print(
        f"{len(inv.services)} services, {inv.file_count()} files -> {args.out / 'inventory.json'}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "scan":
        return run_scan(args)
    print(_version())
    return 0


# Lets you also run it as `python -m tc_detector.cli`.
if __name__ == "__main__":
    raise SystemExit(main())
