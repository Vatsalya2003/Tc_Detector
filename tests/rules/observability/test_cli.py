"""Tests for `tc-rules-observability`."""

from tc_detector.contracts.candidate import Candidate
from tc_detector.rules.observability.cli import main
from tests.rules.observability.fake_repos import COMMIT, JAVA, check, dep, pom, shop, write


def test_runs_both_rules_and_writes_json_lines(tmp_path):
    repo = shop(tmp_path / "repo", orders_pom=pom(dep("spring-boot-starter-zipkin")))
    write(repo, f"shop-payments/{JAVA}/F.java", 'class F { void f() { MDC.put("traceId", t); } }')
    out = tmp_path / "out" / "cands.jsonl"
    assert (
        main(["--repo", str(repo), "--repo-name", "shop", "--commit", COMMIT, "--out", str(out)])
        == 0
    )
    cands = check([Candidate.from_json(line) for line in out.read_text().splitlines()])
    assert [(c.pattern, c.service) for c in cands] == [
        ("distributed-tracing", "orders-service"),
        ("structured-logging", "payments"),
    ]
