"""`tc-rules-resilience`: run the resilience rules on a checkout, print candidates.

    uv run tc-rules-resilience --repo targets/spring-petclinic-microservices

Until development labels freeze (Nov 20), keep this output to yourself: the
labeller for these patterns must not see rule output before labelling.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tc_detector.rules.resilience.circuit_breaker import detect


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tc-rules-resilience")
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--repo-name", help="targets.yaml name; defaults to the folder name")
    p.add_argument("--commit", help="pinned SHA; defaults to the checkout's HEAD")
    p.add_argument("--out", type=Path, help="write candidates as JSON Lines here")
    args = p.parse_args(argv)

    cands = detect(args.repo, args.repo_name, args.commit)
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
