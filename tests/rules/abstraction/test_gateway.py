"""S12: gateway rule, on small fake repos built in tmp_path (offline, no targets/)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tc_detector.contracts.candidate import SNIPPET_MAX_CHARS, Candidate, Category, Unit
from tc_detector.rules.abstraction.gateway import RULE_ID, detect, filter_name, name_words
from tc_detector.scanner import scan

COMMIT = "0" * 40
RES = "src/main/resources"
JAVA = "src/main/java/x"


def write(repo: Path, files: dict[str, str]) -> Path:
    """Create a fake repo: {relative path: content}."""
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
    return repo


def pom(*artifacts: str) -> str:
    deps = "".join(f"<dependency><artifactId>{a}</artifactId></dependency>\n" for a in artifacts)
    return f"<project>\n<dependencies>\n{deps}</dependencies>\n</project>\n"


def app_name(name: str) -> str:
    return f"spring:\n  application:\n    name: {name}\n"


def plain_service(folder: str, name: str | None = None) -> dict[str, str]:
    """An ordinary service with no gateway signals."""
    files = {f"{folder}/pom.xml": pom("spring-boot-starter-web")}
    if name:
        files[f"{folder}/{RES}/application.yml"] = app_name(name)
    return files


def run(repo: Path) -> dict[str, Candidate]:
    return {c.service: c for c in detect(repo, "demo", COMMIT)}


BACKENDS = {
    **plain_service("customers", "customers-service"),
    **plain_service("orders", "orders-service"),
}

SCG_ROUTES = """\
spring:
  application:
    name: api-gateway
  cloud:
    gateway:
      server:
        webflux:
          routes:
            - id: customers
              uri: lb://customers-service
              predicates:
                - Path=/api/customer/**
            - id: orders
              uri: lb://orders-service
"""

TWO_CALLS = """\
package x;
class Clients {
    Mono<Owner> owner(int id) { return web.get().uri("http://customers-service/owners/{id}", id); }
    Mono<Order> order(int id) { return web.get().uri("http://orders-service/orders/{id}", id); }
}
"""


# ------------------------------------------------------------------ positives


def test_spring_cloud_gateway_with_routes(tmp_path):
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "gw/pom.xml": pom("spring-cloud-starter-gateway-server-webflux"),
            f"gw/{RES}/application.yml": SCG_ROUTES,
        },
    )
    found = run(repo)
    assert list(found) == ["api-gateway"]
    snippet = found["api-gateway"].snippet
    assert "strong: gateway routes at src/main/resources/application.yml:8-14" in snippet
    assert "lb://customers-service, lb://orders-service" in snippet
    assert "gateway dependency spring-cloud-starter-gateway-server-webflux at pom.xml:3" in snippet


def test_routes_in_properties_file(tmp_path):
    props = """\
    spring.application.name=router
    spring.cloud.gateway.routes[0].id=customers
    spring.cloud.gateway.routes[0].uri=lb://customers-service
    """
    repo = write(
        tmp_path, {**BACKENDS, "r/pom.xml": pom(), f"r/{RES}/application.properties": props}
    )
    found = run(repo)
    assert list(found) == ["router"]
    assert "application.properties:3-3 -> lb://customers-service" in found["router"].snippet


ROUTE_LOCATOR_BEAN = """\
package x;

import org.springframework.cloud.gateway.route.RouteLocator;
import org.springframework.cloud.gateway.route.builder.RouteLocatorBuilder;

@Configuration
class Routes {
    @Bean
    RouteLocator customRoutes(RouteLocatorBuilder builder) {
        return builder.routes()
            .route("owner", r -> r.path("/api/owners/{id}")
                .filters(f -> { return f.stripPrefix(2); })
                .uri("lb://customers-service"))
            .build();
    }

    @Bean
    WebClient webClient() { return WebClient.create(); }
}
"""


def routing_service(java_path: str, java: str) -> dict[str, str]:
    """A service with no name signal and no YAML routes, so only Java routes can flag it."""
    return {
        **BACKENDS,
        "routing/pom.xml": pom("spring-cloud-starter-gateway"),
        f"routing/{RES}/application.yml": app_name("routing-service"),
        f"routing/{java_path}": java,
    }


def test_java_route_locator_bean(tmp_path):
    repo = write(tmp_path, routing_service(f"{JAVA}/Routes.java", ROUTE_LOCATOR_BEAN))
    found = run(repo)
    assert list(found) == ["routing-service"]
    assert (
        "strong: gateway routes (Java RouteLocator bean) at src/main/java/x/Routes.java:8-15"
        " -> lb://customers-service"
    ) in found["routing-service"].snippet


def test_route_locator_builder_only_imported(tmp_path):
    java = (
        "package x;\n"
        "import org.springframework.cloud.gateway.route.builder.RouteLocatorBuilder;\n"
        "class Util { RouteLocatorBuilder builder; }\n"
    )
    repo = write(tmp_path, routing_service(f"{JAVA}/Util.java", java))
    assert run(repo) == {}


def test_route_locator_bean_in_test_code_is_ignored(tmp_path):
    repo = write(tmp_path, routing_service("src/test/java/x/Routes.java", ROUTE_LOCATOR_BEAN))
    assert run(repo) == {}


def test_route_locator_bean_without_a_route_uri(tmp_path):
    java = (
        "package x;\n"
        "class Routes {\n"
        "    @Bean\n"
        "    RouteLocator none(RouteLocatorBuilder builder) { return builder.routes().build(); }\n"
        "}\n"
    )
    repo = write(tmp_path, routing_service(f"{JAVA}/Routes.java", java))
    assert run(repo) == {}


def test_zuul_service(tmp_path):
    zuul_app = """\
    package x;
    @EnableZuulProxy
    @SpringBootApplication
    class RouterApplication {}
    """
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "router/pom.xml": pom("spring-cloud-starter-netflix-zuul"),
            f"router/{RES}/application.yml": app_name("router"),
            f"router/{JAVA}/RouterApplication.java": zuul_app,
        },
    )
    found = run(repo)
    assert list(found) == ["router"]
    assert "@EnableZuulProxy at src/main/java/x/RouterApplication.java:2" in found["router"].snippet


def test_zuul_routes_config(tmp_path):
    zuul_yml = app_name("router") + "zuul:\n  routes:\n    customers:\n      path: /c/**\n"
    repo = write(
        tmp_path, {**BACKENDS, "router/pom.xml": pom(), f"router/{RES}/application.yml": zuul_yml}
    )
    assert list(run(repo)) == ["router"]


def test_calls_are_supporting_evidence_on_a_gateway(tmp_path):
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "gw/pom.xml": pom("spring-cloud-starter-gateway"),
            f"gw/{RES}/application.yml": SCG_ROUTES,
            f"gw/{JAVA}/Clients.java": TWO_CALLS,
        },
    )
    snippet = run(repo)["api-gateway"].snippet
    assert "supporting: calls 2 other services: customers-service (" in snippet
    assert "orders-service (src/main/java/x/Clients.java:4)" in snippet


def test_name_plus_dependency_is_enough(tmp_path):
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "edge/pom.xml": pom("spring-cloud-starter-gateway"),
            f"edge/{RES}/application.yml": app_name("edge-service"),
        },
    )
    assert list(run(repo)) == ["edge-service"]


# ------------------------------------------------------------------ negatives


def test_ordinary_service_with_adapter_and_facade_classes(tmp_path):
    adapter = 'package x;\nclass PaymentAdapter { String url = "http://customers-service/"; }\n'
    facade = 'package x;\nclass OrderFacade { String url = "http://customers-service/x"; }\n'
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "billing/pom.xml": pom("spring-boot-starter-web"),
            f"billing/{RES}/application.yml": app_name("billing-service"),
            f"billing/{JAVA}/PaymentAdapter.java": adapter,
            f"billing/{JAVA}/OrderFacade.java": facade,
            f"billing/{JAVA}/Clients.java": TWO_CALLS,
        },
    )
    assert run(repo) == {}


def test_config_server(tmp_path):
    config_app = "package x;\n@EnableConfigServer\nclass ConfigServerApplication {}\n"
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "config-server/pom.xml": pom("spring-cloud-config-server"),
            f"config-server/{RES}/application.yml": "server.port: 8888\n",
            f"config-server/{JAVA}/ConfigServerApplication.java": config_app,
        },
    )
    assert run(repo) == {}


def test_gateway_client_library_only(tmp_path):
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "catalog/pom.xml": pom("spring-cloud-starter-gateway-server-webflux"),
            f"catalog/{RES}/application.yml": app_name("catalog-service"),
        },
    )
    assert run(repo) == {}


def test_dependency_and_calls_without_name_is_not_enough(tmp_path):
    """Like PetClinic's genai-service: gateway dependency and two calls, but no routes."""
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "ai/pom.xml": pom("spring-cloud-starter-gateway-server-webflux"),
            f"ai/{RES}/application.yml": app_name("genai-service"),
            f"ai/{JAVA}/Clients.java": TWO_CALLS,
        },
    )
    assert run(repo) == {}


def test_name_word_is_matched_whole_not_as_substring(tmp_path):
    """`knowledge-service` contains "edge" but is not an edge service."""
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "kb/pom.xml": pom("spring-cloud-starter-gateway"),
            f"kb/{RES}/application.yml": app_name("knowledge-service"),
            f"kb/{JAVA}/Clients.java": TWO_CALLS,
        },
    )
    assert run(repo) == {}


@pytest.mark.parametrize(
    ("name", "words"),
    [
        ("knowledge-service", []),
        ("gatewayish-service", []),
        ("proxyman", []),
        ("api-gateway", ["gateway"]),
        ("web_bff", ["bff"]),
        ("Edge-Proxy", ["edge", "proxy"]),
    ],
)
def test_name_words(name, words):
    assert name_words(name) == words


def test_name_plus_calls_without_dependency_is_not_enough(tmp_path):
    """The removed path: a BFF/adapter name plus calls to 2+ services, but no routes.

    The guideline defines a gateway by routing; it doesn't support flagging an
    anti-corruption layer or BFF by its name and the calls it makes.
    """
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "web/pom.xml": pom("spring-boot-starter-webflux"),
            f"web/{RES}/application.yml": app_name("web-bff"),
            f"web/{JAVA}/Clients.java": TWO_CALLS,
        },
    )
    assert run(repo) == {}


def test_adapter_name_plus_calls_without_dependency_is_not_enough(tmp_path):
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "pay/pom.xml": pom("spring-boot-starter-web"),
            f"pay/{RES}/application.yml": app_name("payment-adapter"),
            f"pay/{JAVA}/Clients.java": TWO_CALLS,
        },
    )
    assert run(repo) == {}


# ------------------------------------------------------- filters (supporting only)

PETCLINIC_FILTERS = """\
spring:
  application:
    name: api-gateway
  cloud:
    gateway:
      server:
        webflux:
          default-filters:
            - name: CircuitBreaker
              args:
                name: defaultCircuitBreaker
            - name: Retry
              args:
                retries: 1
          routes:
            - id: vets
              uri: lb://customers-service
              filters:
                - StripPrefix=2
            - id: orders
              uri: lb://orders-service
"""


def test_filters_are_supporting_evidence_in_yaml(tmp_path):
    repo = write(
        tmp_path,
        {**BACKENDS, "gw/pom.xml": pom(), f"gw/{RES}/application.yml": PETCLINIC_FILTERS},
    )
    snippet = run(repo)["api-gateway"].snippet
    assert (
        f"supporting: default filters at {RES}/application.yml:8-14 -> CircuitBreaker, Retry"
        in (snippet)
    )
    assert f"supporting: route filters at {RES}/application.yml:18-19 -> StripPrefix" in snippet
    assert "strong: gateway routes at" in snippet


def test_filters_are_supporting_evidence_in_properties(tmp_path):
    props = """\
    spring.application.name=router
    spring.cloud.gateway.default-filters[0]=Retry=3
    spring.cloud.gateway.default-filters[1].name=CircuitBreaker
    spring.cloud.gateway.routes[0].uri=lb://customers-service
    spring.cloud.gateway.routes[0].filters[0]=StripPrefix=1
    """
    repo = write(
        tmp_path, {**BACKENDS, "r/pom.xml": pom(), f"r/{RES}/application.properties": props}
    )
    snippet = run(repo)["router"].snippet
    assert "supporting: default filters at src/main/resources/application.properties:2-3" in (
        snippet
    )
    assert "-> Retry, CircuitBreaker" in snippet
    assert "supporting: route filters at src/main/resources/application.properties:5-5" in snippet


def test_filters_alone_are_not_a_signal(tmp_path):
    yml = app_name("shop") + (
        "  cloud:\n    gateway:\n      default-filters:\n        - name: Retry\n"
        "      routes:\n        - id: x\n          filters:\n            - StripPrefix=1\n"
    )
    repo = write(tmp_path, {**BACKENDS, "s/pom.xml": pom(), f"s/{RES}/application.yml": yml})
    assert run(repo) == {}


@pytest.mark.parametrize(
    ("yml", "name"),
    [("- StripPrefix=2", "StripPrefix"), ("- name: Retry", "Retry"), ("- Dedupe", "Dedupe")],
)
def test_filter_name(yml, name):
    import yaml

    (item,) = yaml.compose(yml).value
    assert filter_name(item) == name


def test_test_code_is_ignored(tmp_path):
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "gw/pom.xml": pom(),
            f"gw/{RES}/application.yml": app_name("shop"),
            "gw/src/test/resources/application.yml": SCG_ROUTES,
        },
    )
    assert run(repo) == {}


# ------------------------------------------------------------- output format


AGGREGATOR_POM = "<project>\n<modules>\n<module>a</module>\n</modules>\n</project>\n"


def petclinic_like(tmp_path: Path) -> Path:
    """Folders share a prefix; config-server has no spring.application.name."""
    return write(
        tmp_path,
        {
            "pom.xml": AGGREGATOR_POM,  # a parent pom, like PetClinic's: not a service
            **plain_service("spring-petclinic-customers-service", "customers-service"),
            **plain_service("spring-petclinic-orders-service", "orders-service"),
            **plain_service("spring-petclinic-config-server"),
            "spring-petclinic-api-gateway/pom.xml": pom("spring-cloud-starter-gateway"),
            f"spring-petclinic-api-gateway/{RES}/application.yml": SCG_ROUTES,
            "spring-petclinic-web-bff/pom.xml": pom(),
            f"spring-petclinic-web-bff/{RES}/application.yml": app_name("web-bff"),
            f"spring-petclinic-web-bff/{JAVA}/Clients.java": TWO_CALLS,
        },
    )


def test_service_names_follow_the_convention(tmp_path):
    names = {s.root: s.name for s in scan(petclinic_like(tmp_path), "demo", COMMIT).services}
    assert names == {
        "spring-petclinic-api-gateway": "api-gateway",  # spring.application.name
        "spring-petclinic-config-server": "config-server",  # folder minus shared prefix
        "spring-petclinic-customers-service": "customers-service",
        "spring-petclinic-orders-service": "orders-service",
        "spring-petclinic-web-bff": "web-bff",
    }


# --------------------------------------- service names come from the scanner


def scanner_names(repo: Path) -> set[str]:
    return {s.name for s in scan(repo, "demo", COMMIT).services}


def gateway_routes_service(folder: str) -> dict[str, str]:
    """A gateway with routes and no spring.application.name: named from its folder."""
    yml = "spring:\n  cloud:\n    gateway:\n      routes:\n        - id: a\n          uri: lb://a\n"
    return {f"{folder}/pom.xml": pom(), f"{folder}/{RES}/application.yml": yml}


def test_nested_parent_pom_is_not_a_service(tmp_path):
    """A parent pom in a subfolder only groups modules; the shared prefix still applies."""
    repo = write(
        tmp_path,
        {
            "services/pom.xml": AGGREGATOR_POM,
            **gateway_routes_service("services/shop-gateway"),
            **plain_service("services/shop-orders"),
        },
    )
    assert scanner_names(repo) == {"gateway", "orders"}
    assert [c.service for c in detect(repo, "demo", COMMIT)] == ["gateway"]


def test_service_under_a_tests_folder_is_found(tmp_path):
    repo = write(
        tmp_path,
        {**plain_service("shop-orders"), **gateway_routes_service("tests/shop-gateway")},
    )
    assert scanner_names(repo) == {"gateway", "orders"}
    assert [c.service for c in detect(repo, "demo", COMMIT)] == ["gateway"]


def test_java_route_in_a_build_package_is_read(tmp_path):
    """`com/acme/build/` is a Java package, not build output, so its routes count."""
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "routing/pom.xml": pom(),
            f"routing/{RES}/application.yml": app_name("routing-service"),
            "routing/src/main/java/com/acme/build/Routes.java": ROUTE_LOCATOR_BEAN,
        },
    )
    found = run(repo)
    assert list(found) == ["routing-service"]
    assert "strong: gateway routes (Java RouteLocator bean) at src/main/java/com/acme/build/" in (
        found["routing-service"].snippet
    )


def test_candidate_names_are_the_scanners(tmp_path):
    repo = petclinic_like(tmp_path)
    assert {c.service for c in detect(repo, "demo", COMMIT)} <= scanner_names(repo)


def test_candidates_pass_the_candidate_checks(tmp_path):
    candidates = detect(petclinic_like(tmp_path), "demo", COMMIT)
    assert sorted(c.service for c in candidates) == ["api-gateway"]  # web-bff: name + calls only
    for c in candidates:
        assert Candidate.from_dict(c.to_dict()) == c  # re-runs every check in checks.py
        assert c.unit == Unit.SERVICE
        assert (c.file, c.line_start, c.line_end) == (None, None, None)
        assert c.pattern == "gateway"
        assert c.category == Category.ABSTRACTION
        assert c.rule_id == RULE_ID == "abstraction-gateway-01"
        assert c.repo == "demo"
        assert c.commit == COMMIT
        assert c.id == f"demo:{c.service}:-:service:gateway"
    assert len({c.id for c in candidates}) == len(candidates)


def test_repo_name_defaults_to_folder_name(tmp_path):
    repo = petclinic_like(tmp_path / "spring-petclinic-microservices")
    assert {c.repo for c in detect(repo, commit=COMMIT)} == {"spring-petclinic-microservices"}


def test_snippet_stays_within_the_limit(tmp_path):
    routes = "".join(
        f"  - id: r{i}\n    uri: lb://some-long-service-name-{i:04d}\n" for i in range(200)
    )
    yml = (
        app_name("api-gateway")
        + "  cloud:\n    gateway:\n      routes:\n"
        + textwrap.indent(routes, "      ")
    )
    repo = write(tmp_path, {**BACKENDS, "gw/pom.xml": pom(), f"gw/{RES}/application.yml": yml})
    snippet = run(repo)["api-gateway"].snippet
    assert len(snippet) <= SNIPPET_MAX_CHARS
    assert snippet.endswith("[... truncated]")
