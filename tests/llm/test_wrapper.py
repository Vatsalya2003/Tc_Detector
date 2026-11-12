"""S1 and S5: the wrapper returns contract-shaped verdicts, caches answers, and logs cost."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tc_detector.contracts.candidate import Candidate
from tc_detector.llm import Attributor, Settings
from tc_detector.llm.context import numbered_snippet
from tc_detector.llm.costlog import summarize
from tc_detector.llm.pricing import UnknownModelPrice, cost_usd
from tc_detector.llm.verdict import ADR_FIELDS, COST_FIELDS, STAGE3_FIELDS
from tests.llm.fakes import ADR_ANSWER, GOOD_ANSWER, FakeClient, make_response


@pytest.fixture
def candidate() -> dict[str, Any]:
    return Candidate.create(
        repo="shop",
        commit="abc1234",
        service="orders",
        file="src/main/java/shop/orders/PaymentClient.java",
        line_start=6,
        line_end=7,
        unit="line_range",
        pattern="circuit-breaker",
        category="automation",
        rule_id="automation-cb-annotation-01",
        snippet='@CircuitBreaker(name = "payments")\npublic Result charge(Order o) {',
    ).to_dict()


def attributor(tmp_path, client, **overrides):
    settings = Settings(
        cache_dir=tmp_path / "cache", cost_log=tmp_path / "cost_log.jsonl", **overrides
    )
    return Attributor(settings, client=client)


# ------------------------------------------------------------------ contract


def test_verdict_has_exactly_the_contract_fields(tmp_path, candidate):
    v = attributor(tmp_path, FakeClient(make_response(GOOD_ANSWER))).attribute(candidate)
    assert set(v) == {"candidate_id", *STAGE3_FIELDS, *COST_FIELDS}
    assert v["candidate_id"] == candidate["id"]
    assert v["is_tc"] is True and v["error"] is None and v["cache_hit"] is False


def test_accepts_a_candidate_object(tmp_path, candidate):
    client = FakeClient(make_response(GOOD_ANSWER))
    v = attributor(tmp_path, client).attribute(Candidate.from_dict(candidate))
    assert v["candidate_id"] == candidate["id"]


def test_invalid_candidate_fails_before_any_api_call(tmp_path, candidate):
    client = FakeClient(make_response(GOOD_ANSWER))
    with pytest.raises(ValueError):
        attributor(tmp_path, client).attribute({**candidate, "rule_id": "C-cb-01"})
    assert client.calls == []


def test_request_uses_structured_output_and_cacheable_system(tmp_path, candidate):
    client = FakeClient(make_response(GOOD_ANSWER))
    attributor(tmp_path, client).attribute(candidate)
    call = client.calls[0]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["fallbacks"] == "default"
    assert '6 | @CircuitBreaker(name = "payments")' in call["messages"][0]["content"]


def test_only_the_six_team_categories_are_allowed(tmp_path, candidate):
    client = FakeClient(make_response(GOOD_ANSWER))
    attributor(tmp_path, client).attribute(candidate)
    enum = client.calls[0]["output_config"]["format"]["schema"]["properties"]["tc_category"]
    assert sorted(enum["enum"]) == sorted(
        [
            "observability",
            "api-stability",
            "modularity",
            "automation",
            "abstraction",
            "configurability",
        ]
    )


def test_no_fallbacks_uses_plain_endpoint(tmp_path, candidate):
    client = FakeClient(make_response(GOOD_ANSWER))
    attributor(tmp_path, client, fallbacks=False).attribute(candidate)
    assert "fallbacks" not in client.calls[0] and "betas" not in client.calls[0]


def test_snippet_gets_real_line_numbers():
    c = {"snippet": "a\nb", "line_start": 9}
    assert numbered_snippet(c) == " 9 | a\n10 | b"
    assert numbered_snippet({"snippet": "a", "line_start": None}) == "a"


# --------------------------------------------------------------------- cost


def test_cost_matches_price_table(tmp_path, candidate):
    resp = make_response(GOOD_ANSWER, input_tokens=1000, output_tokens=200)
    v = attributor(tmp_path, FakeClient(resp)).attribute(candidate)
    # Sonnet 5.5: $2 in, $10 out per million.
    assert v["cost_usd"] == pytest.approx((1000 * 2 + 200 * 10) / 1e6)
    assert v["input_tokens"] == 1000 and v["output_tokens"] == 200


def test_cost_uses_the_model_that_served_the_call(tmp_path, candidate):
    resp = make_response(GOOD_ANSWER, model="claude-sonnet-5")
    v = attributor(tmp_path, FakeClient(resp)).attribute(candidate)
    assert v["model"] == "claude-sonnet-5"


def test_prompt_cache_tokens_are_priced_separately():
    assert cost_usd("claude-sonnet-5-5", 0, 0, 1_000_000, 0) == pytest.approx(2.50)
    assert cost_usd("claude-sonnet-5-5", 0, 0, 0, 1_000_000) == pytest.approx(0.10)


def test_unknown_model_is_an_error_not_a_guess():
    with pytest.raises(UnknownModelPrice):
        cost_usd("claude-made-up", 1, 1)


# -------------------------------------------------------------------- cache


def test_repeat_run_uses_no_new_tokens(tmp_path, candidate):
    """S5 done-when: a repeat run uses no new tokens."""
    client = FakeClient(make_response(GOOD_ANSWER))
    first = attributor(tmp_path, client).attribute(candidate)
    second = attributor(tmp_path, client).attribute(candidate)  # fresh process, same disk

    assert len(client.calls) == 1
    assert second["cache_hit"] is True
    assert second["input_tokens"] == second["output_tokens"] == 0
    assert second["cost_usd"] == 0
    assert {k: second[k] for k in STAGE3_FIELDS} == {k: first[k] for k in STAGE3_FIELDS}

    totals = summarize(tmp_path / "cost_log.jsonl")
    assert totals["api_calls"] == 1 and totals["cache_hits"] == 1
    assert totals["saved_usd"] == pytest.approx(first["cost_usd"])


def test_repeats_are_separate_calls_for_consistency_experiment(tmp_path, candidate):
    client = FakeClient(make_response(GOOD_ANSWER), make_response(GOOD_ANSWER))
    a = attributor(tmp_path, client)
    a.attribute(candidate, repeat=0)
    v1 = a.attribute(candidate, repeat=1)
    assert len(client.calls) == 2 and v1["repeat"] == 1 and v1["cache_hit"] is False


@pytest.mark.parametrize("change", [{"model": "claude-haiku-5-5"}, {"effort": "low"}])
def test_cache_key_covers_model_and_effort(tmp_path, candidate, change):
    attributor(tmp_path, FakeClient(make_response(GOOD_ANSWER))).attribute(candidate)
    model = change.get("model", "claude-sonnet-5-5")
    client = FakeClient(make_response(GOOD_ANSWER, model=model))
    attributor(tmp_path, client, **change).attribute(candidate)
    assert len(client.calls) == 1


def test_no_cache_always_calls(tmp_path, candidate):
    client = FakeClient(make_response(GOOD_ANSWER), make_response(GOOD_ANSWER))
    a = attributor(tmp_path, client, use_cache=False)
    a.attribute(candidate)
    a.attribute(candidate)
    assert len(client.calls) == 2


# ------------------------------------------------------------------- errors


def test_refusal_is_recorded_and_not_cached(tmp_path, candidate):
    client = FakeClient(
        make_response("", stop_reason="refusal", output_tokens=5), make_response(GOOD_ANSWER)
    )
    a = attributor(tmp_path, client)
    v = a.attribute(candidate)
    assert v["error"] == "refusal" and v["is_tc"] is None and v["tc_signals"] == []
    assert v["cost_usd"] > 0  # tokens were still spent
    assert a.attribute(candidate)["error"] is None  # retried, not served from cache
    assert len(client.calls) == 2


def test_invalid_json_is_an_error(tmp_path, candidate):
    v = attributor(tmp_path, FakeClient(make_response("not json"))).attribute(candidate)
    assert v["error"] == "invalid_json" and v["is_tc"] is None


def test_out_of_schema_answer_is_an_error(tmp_path, candidate):
    bad = {**GOOD_ANSWER, "tc_confidence": 9}
    v = attributor(tmp_path, FakeClient(make_response(bad))).attribute(candidate)
    assert v["error"] == "invalid_json"


# ---------------------------------------------------------------------- ADR


def test_adr_fields_only_for_confirmed_tc(tmp_path, candidate):
    client = FakeClient(make_response(GOOD_ANSWER), make_response(ADR_ANSWER))
    v = attributor(tmp_path, client).attribute(candidate, adr=True)
    assert len(client.calls) == 2
    assert v["adr_title"] == ADR_ANSWER["adr_title"]
    assert v["output_tokens"] == 400  # both calls counted


def test_adr_skipped_when_not_tc(tmp_path, candidate):
    no = {**GOOD_ANSWER, "is_tc": False, "not_tc_reason": "Default config only."}
    client = FakeClient(make_response(no))
    v = attributor(tmp_path, client).attribute(candidate, adr=True)
    assert len(client.calls) == 1
    assert all(v[k] is None for k in ADR_FIELDS)


def test_default_call_never_requests_adr_fields(tmp_path, candidate):
    client = FakeClient(make_response(GOOD_ANSWER))
    attributor(tmp_path, client).attribute(candidate)
    schema = client.calls[0]["output_config"]["format"]["schema"]
    assert not set(ADR_FIELDS) & set(schema["properties"])


def test_cli_rejects_a_malformed_candidate_file(tmp_path, candidate):
    from tc_detector.llm.cli import load_candidates

    path = tmp_path / "c.json"
    path.write_text(json.dumps({**candidate, "snippet": ""}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_candidates(path)
