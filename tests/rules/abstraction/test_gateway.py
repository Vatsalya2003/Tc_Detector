"""S12: gateway rule, on small fake repos built in tmp_path (offline, no targets/)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tc_detector.contracts.candidate import SNIPPET_MAX_CHARS, Candidate, Category, Unit
from tc_detector.rules.abstraction.gateway import RULE_ID, detect, find_services, name_words

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


def test_bff_that_calls_several_services(tmp_path):
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "web/pom.xml": pom("spring-boot-starter-webflux"),
            f"web/{RES}/application.yml": app_name("web-bff"),
            f"web/{JAVA}/Clients.java": TWO_CALLS,
        },
    )
    found = run(repo)
    assert list(found) == ["web-bff"]
    snippet = found["web-bff"].snippet
    assert "weak: calls 2 other services: customers-service" in snippet
    assert "weak: service name word(s): bff" in snippet


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


def test_name_with_only_one_call_is_not_enough(tmp_path):
    one_call = 'package x;\nclass C { String u = "http://customers-service/owners"; }\n'
    repo = write(
        tmp_path,
        {
            **BACKENDS,
            "gw/pom.xml": pom("spring-boot-starter-webflux"),
            f"gw/{RES}/application.yml": app_name("api-gateway"),
            f"gw/{JAVA}/C.java": one_call,
        },
    )
    assert run(repo) == {}


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


def petclinic_like(tmp_path: Path) -> Path:
    """Folders share a prefix; config-server has no spring.application.name."""
    return write(
        tmp_path,
        {
            "pom.xml": pom(),
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
    repo = petclinic_like(tmp_path)
    names = {s.root.name: s.name for s in find_services(repo)}
    assert names == {
        "spring-petclinic-api-gateway": "api-gateway",  # spring.application.name
        "spring-petclinic-config-server": "config-server",  # folder minus shared prefix
        "spring-petclinic-customers-service": "customers-service",
        "spring-petclinic-orders-service": "orders-service",
        "spring-petclinic-web-bff": "web-bff",
    }


def test_candidates_pass_the_candidate_checks(tmp_path):
    candidates = detect(petclinic_like(tmp_path), "demo", COMMIT)
    assert sorted(c.service for c in candidates) == ["api-gateway", "web-bff"]
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
