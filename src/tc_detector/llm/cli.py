"""`tc-attribute`: send candidates to Claude and print verdict JSON.

uv run tc-attribute examples/demo-candidate.json
uv run tc-attribute candidates.jsonl --repo ... --out results/petclinic/verdicts.jsonl
uv run tc-attribute cand.json --repo ... --dry-run      # show the prompt, no API call
uv run tc-attribute cand.json --repo ... --repeats 5    # consistency experiment
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tc_detector.contracts.candidate import Candidate
from tc_detector.llm.context import build_context
from tc_detector.llm.costlog import summarize
from tc_detector.llm.prompts import PROMPTS
from tc_detector.llm.wrapper import DEFAULT_MODEL, Attributor, Settings


def load_candidates(path: Path) -> list[dict[str, Any]]:
    """Read candidates and validate each against the frozen Candidate format."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data = json.loads(text)
        rows = data if isinstance(data, list) else [data]
    return [Candidate.from_dict(r).to_dict() for r in rows]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="tc-attribute", description=__doc__.splitlines()[0])
    p.add_argument("candidates", type=Path, help="candidate .json (object or list) or .jsonl")
    p.add_argument("--repo", type=Path, help="checkout of the target repo (snippet, git history)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--prompt-version", default="stage3-v1", choices=sorted(PROMPTS))
    p.add_argument(
        "--repeats", type=int, default=1, help="run each candidate N times (repeat 0..N-1)"
    )
    p.add_argument("--adr", action="store_true", help="also request ADR fields for confirmed TC")
    p.add_argument("--no-cache", action="store_true", help="always call the API, never store")
    p.add_argument(
        "--no-fallbacks", action="store_true", help="disable server-side refusal fallback"
    )
    p.add_argument("--cache-dir", type=Path, default=Path(".tc_cache"))
    p.add_argument("--cost-log", type=Path, default=Path("results/cost_log.jsonl"))
    p.add_argument("--out", type=Path, help="write verdicts as JSON Lines here")
    p.add_argument("--dry-run", action="store_true", help="print the rendered prompt and exit")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings(
        model=args.model,
        effort=args.effort,
        prompt_version=args.prompt_version,
        fallbacks=not args.no_fallbacks,
        use_cache=not args.no_cache,
        cache_dir=args.cache_dir,
        cost_log=args.cost_log,
    )
    attributor = Attributor(settings)
    candidates = load_candidates(args.candidates)

    if args.dry_run:
        prompt = PROMPTS[settings.prompt_version]
        for cand in candidates:
            ctx = build_context(cand, args.repo)
            print(f"===== {cand['id']}  [{prompt.version}]\n--- system\n{prompt.system}")
            print(f"--- user\n{attributor.render_user(prompt, cand, ctx)}\n")
        return 0

    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
    import anthropic

    out = None
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        out = args.out.open("a", encoding="utf-8")
    verdicts = []
    try:
        for cand in candidates:
            ctx = build_context(cand, args.repo)
            for r in range(args.repeats):
                v = attributor.attribute(cand, ctx, repeat=r, adr=args.adr)
                verdicts.append(v)
                if out:
                    out.write(json.dumps(v, ensure_ascii=False) + "\n")
                    out.flush()
    except anthropic.AuthenticationError:
        print("Authentication failed: is ANTHROPIC_API_KEY set in .env?", file=sys.stderr)
        return 2
    finally:
        if out:
            out.close()

    if not out:
        print(json.dumps(verdicts[0] if len(verdicts) == 1 else verdicts, indent=2))
    if settings.cost_log and settings.cost_log.exists():
        t = summarize(settings.cost_log)
        print(
            f"[cost log {settings.cost_log}] calls={t['calls']} api={t['api_calls']} "
            f"cache_hits={t['cache_hits']} spent=${t['cost_usd']:.4f} saved=${t['saved_usd']:.4f}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
