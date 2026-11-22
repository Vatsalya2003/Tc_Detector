"""Check that the shared API key works, with one small call.

    uv run python scripts/check_api_key.py

Reads ANTHROPIC_API_KEY from .env (git-ignored). Prints whether the two models we
plan to use are reachable, then makes one tiny request and prints its cost.
Never prints the key.
"""

from __future__ import annotations

import sys

import anthropic
from dotenv import find_dotenv, load_dotenv

from tc_detector.llm.pricing import cost_usd
from tc_detector.llm.wrapper import DEFAULT_MODEL, SMALL_MODEL


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    client = anthropic.Anthropic()

    # Model lookups are free and confirm the key can see both models.
    for model in (DEFAULT_MODEL, SMALL_MODEL):
        try:
            info = client.models.retrieve(model)
            print(f"ok    {model:<20} ({info.display_name})")
        except anthropic.AuthenticationError:
            print("FAIL  authentication: the key in .env is missing or invalid")
            return 2
        except anthropic.NotFoundError:
            print(f"FAIL  {model}: not available to this key")
        except anthropic.APIError as e:
            print(f"FAIL  {model}: {e}")

    try:
        resp = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=256,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        )
    except anthropic.RateLimitError:
        print("FAIL  rate limited or out of credit: check the Console spend limit")
        return 3
    except anthropic.APIError as e:
        print(f"FAIL  test call: {e}")
        return 1

    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    u = resp.usage
    cost = cost_usd(resp.model, u.input_tokens, u.output_tokens)
    print(
        f"ok    test call -> {text!r}  ({u.input_tokens} in / {u.output_tokens} out, ${cost:.6f})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
