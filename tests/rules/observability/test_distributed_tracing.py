"""Tests for the distributed-tracing rule (GUIDELINES.md, `distributed-tracing`)."""

from tc_detector.contracts.candidate import Category, Unit
from tc_detector.rules.observability.distributed_tracing import RULE_ID, detect
from tc_detector.scanner import scan
from tests.rules.observability.fake_repos import (
    COMMIT,
    JAVA,
    RES,
    check,
    dep,
    pom,
    shop,
    write,
)


def run(root):
    return check(detect(root, "shop", COMMIT))


def services(root):
    return [c.service for c in run(root)]


# ------------------------------------------------------------------ positives


def test_zipkin_starter_alone_makes_a_service_candidate(tmp_path):
    shop(tmp_path, orders_pom=pom(dep("spring-boot-starter-zipkin", "org.springframework.boot")))
    [c] = run(tmp_path)
    assert (c.service, c.unit, c.file, c.line_start, c.line_end) == (
        "orders-service",
        Unit.SERVICE,
        None,
        None,
        None,
    )
    assert (c.pattern, c.category, c.rule_id) == (
        "distributed-tracing",
        Category.OBSERVABILITY,
        RULE_ID,
    )
    # <artifactId> is on line 6 of the generated pom.
    assert "signal: dependency spring-boot-starter-zipkin (pom.xml:6)" in c.snippet


def test_micrometer_tracing_bridge_counts(tmp_path):
    shop(tmp_path, payments_pom=pom(dep("micrometer-tracing-bridge-otel", "io.micrometer")))
    assert services(tmp_path) == ["payments"]


def test_opentelemetry_in_gradle_counts(tmp_path):
    write(tmp_path, "settings.gradle", "include 'api', 'worker'\n")
    write(
        tmp_path,
        "api/build.gradle",
        "dependencies {\n"
        "  implementation 'io.opentelemetry:opentelemetry-exporter-otlp:1.40.0'\n"
        "}\n",
    )
    write(
        tmp_path,
        "worker/build.gradle.kts",
        'dependencies {\n  implementation("io.micrometer:micrometer-tracing-bridge-brave")\n}\n',
    )
    cands = run(tmp_path)
    assert [c.service for c in cands] == ["api", "worker"]
    assert "opentelemetry-exporter-otlp (build.gradle:2)" in cands[0].snippet


def test_tracing_code_without_a_dependency_counts(tmp_path):
    shop(tmp_path)
    write(
        tmp_path,
        f"shop-orders/{JAVA}/Orders.java",
        'class Orders {\n  @Observed(name = "x")\n  void a() {}\n}\n',
    )
    write(
        tmp_path,
        f"shop-payments/{JAVA}/Pay.java",
        'class Pay {\n  @NewSpan\n  void b() { Span s = tracer.nextSpan().name("p"); }\n}\n',
    )
    cands = run(tmp_path)
    assert [c.service for c in cands] == ["orders-service", "payments"]
    assert "@Observed (src/main/java/com/shop/Orders.java:2)" in cands[0].snippet
    assert "@NewSpan (src/main/java/com/shop/Pay.java:2)" in cands[1].snippet
    assert "manual span nextSpan() (src/main/java/com/shop/Pay.java:3)" in cands[1].snippet


def test_fully_qualified_annotation_counts(tmp_path):
    shop(tmp_path)
    write(
        tmp_path,
        f"shop-orders/{JAVA}/A.java",
        "class A { @io.micrometer.observation.annotation.Observed void a() {} }",
    )
    assert services(tmp_path) == ["orders-service"]


def test_one_candidate_per_service_listing_every_signal(tmp_path):
    deps = dep("spring-boot-starter-zipkin") + dep("micrometer-tracing-bridge-brave")
    shop(tmp_path, orders_pom=pom(deps))
    write(tmp_path, f"shop-orders/{JAVA}/A.java", "class A { @Observed void a() {} }")
    [c] = run(tmp_path)
    assert c.snippet.count("signal:") == 3


# ------------------------------------------------------------------ negatives


def test_prometheus_registry_is_metrics_not_tracing(tmp_path):
    shop(tmp_path, orders_pom=pom(dep("micrometer-registry-prometheus", "io.micrometer")))
    assert run(tmp_path) == []


def test_reactor_context_propagation_alone_does_not_count(tmp_path):
    shop(tmp_path, orders_pom=pom(dep("context-propagation", "io.micrometer")))
    yml = (
        "spring:\n  application:\n    name: orders-service\n"
        "  reactor:\n    context-propagation: auto\n"
    )
    write(tmp_path, f"shop-orders/{RES}/application.yml", yml)
    assert run(tmp_path) == []


def test_zipkin_server_in_root_docker_compose_is_not_a_service(tmp_path):
    shop(tmp_path)
    write(
        tmp_path,
        "docker-compose.yml",
        "services:\n  tracing-server:\n    image: openzipkin/zipkin\n",
    )
    assert run(tmp_path) == []


def test_managed_versions_exclusions_and_boms_do_not_count(tmp_path):
    managed = (
        "  <dependencyManagement><dependencies>\n"
        + dep("opentelemetry-instrumentation-bom", "io.opentelemetry")
        + "  </dependencies></dependencyManagement>\n"
    )
    excluded = (
        "    <dependency><artifactId>web</artifactId><exclusions>\n"
        + dep("micrometer-tracing-bridge-brave")
        + "    </exclusions></dependency>\n"
    )
    shop(tmp_path, orders_pom=pom(excluded, extra=managed))
    write(tmp_path, "shop-payments/pom.xml", pom(dep("opentelemetry-bom")))
    assert run(tmp_path) == []


def test_commented_out_dependency_and_code_do_not_count(tmp_path):
    commented = "<!--\n" + dep("spring-boot-starter-zipkin") + "-->\n"
    shop(tmp_path, orders_pom=pom(commented))
    java = 'class A {\n  // @Observed\n  /* tracer.nextSpan() */\n  String s = "@NewSpan";\n}\n'
    write(tmp_path, f"shop-payments/{JAVA}/A.java", java)
    assert run(tmp_path) == []


def test_test_code_does_not_count(tmp_path):
    shop(tmp_path)
    write(tmp_path, "shop-orders/src/test/java/ATest.java", "class ATest { @Observed void a() {} }")
    assert run(tmp_path) == []


# ------------------------------------------------------------------ format and reuse


def test_snippet_stays_within_the_limit(tmp_path):
    shop(tmp_path)
    many = "class A {\n" + "  @Observed void a() {}\n" * 300 + "}\n"
    write(tmp_path, f"shop-orders/{JAVA}/A.java", many)
    [c] = run(tmp_path)
    assert c.snippet.endswith("[... truncated]")


def test_a_passed_in_inventory_gives_the_same_candidates(tmp_path):
    shop(tmp_path, orders_pom=pom(dep("spring-boot-starter-zipkin")))
    inventory = scan(tmp_path, "shop", COMMIT)
    assert detect(tmp_path, inventory=inventory) == run(tmp_path)
