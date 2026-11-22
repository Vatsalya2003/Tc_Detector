"""`tc-rules-observability`: run the observability rules on a checkout, print candidates.

    uv run tc-rules-observability --repo ../spring-petclinic-microservices

The repo is scanned once and the inventory is shared by both rules.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tc_detector.rules.observability import distributed_tracing, structured_logging
from tc_detector.scanner import scan

RULES = (distributed_tracing, structured_logging)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tc-rules-observability")
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--repo-name", help="targets.yaml name; defaults to the folder name")
    p.add_argument("--commit", help="pinned SHA; defaults to the checkout's HEAD")
    p.add_argument("--out", type=Path, help="write candidates as JSON Lines here")
    args = p.parse_args(argv)

    inventory = scan(args.repo, args.repo_name, args.commit)
    cands = [c for rule in RULES for c in rule.detect(args.repo, inventory=inventory)]
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as f:
            for c in cands:
                f.write(c.to_json() + "\n")
    else:
        for c in cands:
            print(c.id, c.rule_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
