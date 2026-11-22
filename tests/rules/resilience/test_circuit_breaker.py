"""S11: circuit breaker and retry rule, on small positive and negative fixtures."""

from __future__ import annotations

import textwrap

from tc_detector.contracts.candidate import SNIPPET_MAX_CHARS, Candidate, Category, Unit
from tc_detector.rules.resilience.circuit_breaker import (
    detect,
    detect_java,
    detect_properties,
    detect_yaml,
)
from tc_detector.rules.resilience.common import trim_snippet


def java(src: str) -> list[tuple[int, int, str]]:
    return [(h.start, h.end, h.rule_id) for h in detect_java(textwrap.dedent(src).encode())]


def yml(src: str) -> list[tuple[int, int, str]]:
    return [(h.start, h.end, h.rule_id) for h in detect_yaml(textwrap.dedent(src))]


# --------------------------------------------------------------------- Java


ANNOTATED = """\
package x;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.github.resilience4j.retry.annotation.Retry;

class PaymentClient {
    @CircuitBreaker(name = "payments", fallbackMethod = "fallback")
    @Retry(name = "payments")
    public String charge(String id) {
        return http.post(id);
    }

    public String fallback(String id, Throwable t) {
        return "queued";
    }
}
"""


def test_annotated_method_is_one_candidate():
    assert java(ANNOTATED) == [(6, 10, "automation-cb-annotation-01")]


PROGRAMMATIC = """\
package x;
import org.springframework.cloud.client.circuitbreaker.ReactiveCircuitBreaker;
import org.springframework.cloud.client.circuitbreaker.ReactiveCircuitBreakerFactory;

class Gateway {
    private final ReactiveCircuitBreakerFactory cbFactory;

    Gateway(ReactiveCircuitBreakerFactory cbFactory) {
        this.cbFactory = cbFactory;
    }

    Mono<Stock> stock(int id) {
        ReactiveCircuitBreaker cb = cbFactory.create("inventory");
        return cb.run(client.get(id), t -> Mono.empty());
    }
}
"""


def test_programmatic_use_marks_the_method_not_the_injection():
    assert java(PROGRAMMATIC) == [(12, 15, "automation-cb-programmatic-01")]


CONFIG_BEAN = """\
package x;
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;
import org.springframework.cloud.circuitbreaker.resilience4j.Resilience4JConfigBuilder;

class Config {
    @Bean
    Customizer<Factory> defaults() {
        return f -> f.configureDefault(id -> new Resilience4JConfigBuilder(id)
            .circuitBreakerConfig(CircuitBreakerConfig.ofDefaults())
            .build());
    }
}
"""


def test_config_bean_is_detected():
    assert java(CONFIG_BEAN) == [(6, 11, "automation-cb-config-java-01")]


CLASS_LEVEL = """\
package x;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;

@CircuitBreaker(name = "inventory")
class InventoryClient {
    String a() { return "a"; }
    @CircuitBreaker(name = "inventory-b")
    String b() { return "b"; }
}
"""


def test_class_level_annotation_absorbs_inner_hits():
    assert java(CLASS_LEVEL) == [(4, 9, "automation-cb-annotation-01")]


GATEWAY_DSL = """\
package x;
import org.springframework.cloud.gateway.route.RouteLocator;

class Routes {
    RouteLocator routes(RouteLocatorBuilder b) {
        return b.routes()
            .route(r -> r.path("/api/**").filters(f -> f.circuitBreaker(c -> c.setName("x")))
                .uri("lb://svc"))
            .build();
    }
}
"""


def test_gateway_java_dsl_is_detected():
    assert java(GATEWAY_DSL) == [(5, 10, "automation-cb-programmatic-01")]


NO_IMPORT = """\
package x;

class Retry {
    // TODO: add a circuit breaker here
    int retryCount = 3;
    @Retry
    void retry() { for (int i = 0; i < retryCount; i++) { call(); } }
}
"""


def test_generic_names_without_a_resilience_import_are_ignored():
    assert java(NO_IMPORT) == []


UNRELATED_WITH_IMPORT = """\
package x;
import io.github.resilience4j.retry.RetryConfig;

class Other {
    void retryLater() { scheduler.retry(5); }
}
"""


def test_import_alone_does_not_trigger():
    assert java(UNRELATED_WITH_IMPORT) == []


# --------------------------------------------------------------------- YAML


GATEWAY_YAML = """\
spring:
  cloud:
    gateway:
      default-filters:
        - name: CircuitBreaker
          args:
            name: sharedBreaker
            fallbackUri: forward:/fallback
        - name: Retry
          args:
            retries: 1
      routes:
        - id: catalog
          uri: lb://catalog
          filters:
            - StripPrefix=2
        - id: reviews
          uri: lb://reviews
          filters:
            - StripPrefix=2
            - CircuitBreaker=name=reviewsCircuitBreaker,fallbackUri=/fallback
"""


def test_gateway_filters_one_candidate_per_filter_list():
    assert yml(GATEWAY_YAML) == [
        (5, 11, "automation-cb-config-yaml-01"),
        (21, 21, "automation-cb-config-yaml-01"),
    ]


RESILIENCE4J_YAML = """\
resilience4j:
  circuitbreaker:
    instances:
      payments:
        slidingWindowSize: 10
  retry:
    instances:
      payments:
        maxAttempts: 3

server:
  port: 8080
"""


def test_resilience4j_blocks():
    # circuitbreaker (2-5) and retry (6-9) are adjacent, so they merge into one unit.
    assert yml(RESILIENCE4J_YAML) == [(2, 9, "automation-cb-config-yaml-01")]


MESH_YAML = """\
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
spec:
  http:
    - route:
        - destination:
            host: reviews
      retries:
        attempts: 3
        perTryTimeout: 2s
"""


def test_istio_retries():
    assert yml(MESH_YAML) == [(8, 10, "automation-cb-mesh-yaml-01")]


def test_feign_circuitbreaker_flag_dotted_and_nested():
    assert yml(
        "spring:\n  cloud:\n    openfeign:\n      circuitbreaker:\n        enabled: true\n"
    ) == [(5, 5, "automation-cb-config-yaml-01")]
    assert yml("feign.circuitbreaker.enabled: true\n") == [(1, 1, "automation-cb-config-yaml-01")]
    assert yml("feign.circuitbreaker.enabled: false\n") == []


NEGATIVE_YAML = """\
spring:
  application:
    name: circuit-breaker-demo
  rabbitmq:
    listener:
      simple:
        retry:
          enabled: true
app:
  retries: 3
"""


def test_unrelated_yaml_is_ignored():
    assert yml(NEGATIVE_YAML) == []


def test_broken_yaml_does_not_crash():
    assert yml("a: [unclosed\n") == []


# --------------------------------------------------------------- properties


def test_properties_group_contiguous_lines():
    text = (
        "server.port=8080\n"
        "resilience4j.circuitbreaker.instances.a.slidingWindowSize=10\n"
        "resilience4j.retry.instances.a.maxAttempts=3\n"
        "logging.level.root=INFO\n"
        "spring.cloud.gateway.routes[0].filters[0]=CircuitBreaker=myCb\n"
    )
    assert [(h.start, h.end) for h in detect_properties(text)] == [(2, 3), (5, 5)]


# ------------------------------------------------------------- whole repo


def test_detect_on_a_mini_repo(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>")
    for svc in ("shop-gateway", "shop-orders"):
        (tmp_path / svc).mkdir()
        (tmp_path / svc / "pom.xml").write_text("<project/>")
    main = tmp_path / "shop-gateway/src/main/java/x"
    main.mkdir(parents=True)
    (main / "Gateway.java").write_text(PROGRAMMATIC)
    test = tmp_path / "shop-gateway/src/test/java/x"
    test.mkdir(parents=True)
    (test / "GatewayTest.java").write_text(ANNOTATED)  # test code: must be ignored
    res = tmp_path / "shop-orders/src/main/resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(RESILIENCE4J_YAML)

    # Candidate.create() validates each one against the frozen format as it is built.
    cands = detect(tmp_path, repo_name="shop", commit="abc1234")
    assert all(isinstance(c, Candidate) for c in cands)
    assert sorted(c.id for c in cands) == [
        "shop:gateway:src/main/java/x/Gateway.java:12-15:circuit-breaker",
        "shop:orders:src/main/resources/application.yml:2-9:circuit-breaker",
    ]
    c = next(c for c in cands if c.service == "gateway")
    assert c.file == "src/main/java/x/Gateway.java"  # relative to the service root
    assert c.unit == Unit.LINE_RANGE and c.category == Category.AUTOMATION
    assert c.commit == "abc1234" and c.rule_id == "automation-cb-programmatic-01"
    assert 'cbFactory.create("inventory")' in c.snippet


def test_long_snippets_are_cut_to_the_contract_limit():
    snippet = trim_snippet([f"line {i} " + "x" * 80 for i in range(100)])
    assert len(snippet) <= SNIPPET_MAX_CHARS
    assert snippet.endswith("[... truncated]")
    assert trim_snippet(["short"]) == "short"
