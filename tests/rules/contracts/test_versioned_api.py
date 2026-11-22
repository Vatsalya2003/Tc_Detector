"""versioned-api rule, on small fake repos built in tmp_path (offline, no targets/)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from tc_detector.contracts.candidate import SNIPPET_MAX_CHARS, Candidate, Category, Unit
from tc_detector.rules.contracts.versioned_api import PATTERN, RULE_ID, detect, main

COMMIT = "0" * 40
SVC = "shop-orders"  # service folder; named orders-service by its application.yml
RES = f"{SVC}/src/main/resources"
PROTO = f"{SVC}/src/main/proto/shop/v1"


def write(repo: Path, files: dict[str, str]) -> Path:
    """Create a fake repo with one service plus `files` ({relative path: content})."""
    base = {
        f"{SVC}/pom.xml": "<project/>\n",
        f"{RES}/application.yml": "spring:\n  application:\n    name: orders-service\n",
    }
    for rel, content in {**base, **files}.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
    return repo


def run(repo: Path) -> dict[str, Candidate]:
    """Candidates keyed by file name, e.g. "openapi.yaml"."""
    return {Path(c.file).name: c for c in detect(repo, "demo", COMMIT)}


# ------------------------------------------------------------- what counts


def test_openapi_yaml_with_info_version_is_a_file_candidate(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{RES}/openapi.yaml": """\
                openapi: 3.0.3
                info:
                  title: Orders API
                  version: 1.2.0
                paths:
                  /orders/{id}:
                    get: {}
            """
        },
    )
    [c] = detect(repo, "demo", COMMIT)
    assert c.file == "src/main/resources/openapi.yaml"  # relative to service root
    assert c.service == "orders-service"  # from spring.application.name
    assert (c.unit, c.line_start, c.line_end) == (Unit.FILE, None, None)
    assert (c.pattern, c.category, c.rule_id) == (PATTERN, Category.API_STABILITY, RULE_ID)
    assert c.id == f"demo:orders-service:{c.file}:file:versioned-api"
    assert "spec: OpenAPI 3.0.3" in c.snippet
    assert "signal: info.version 1.2.0" in c.snippet
    assert "versioned paths" not in c.snippet  # /orders/{id} has no version
    assert "  title: Orders API" in c.snippet  # the file's head is shown


def test_json_spec_with_only_versioned_paths_is_a_candidate(tmp_path):
    # No info.version, and the file name doesn't say "openapi": the `openapi` key does.
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Orders API"},
        "paths": {"/v1/orders": {}, "/api/v2/orders/{id}": {}, "/health": {}},
    }
    repo = write(tmp_path, {f"{RES}/static/api-docs.json": json.dumps(spec, indent=2)})
    c = run(repo)["api-docs.json"]
    assert "spec: OpenAPI 3.1.0" in c.snippet
    assert "signal: versioned paths (2 of 3): /v1/orders, /api/v2/orders/{id}" in c.snippet
    assert "info.version" not in c.snippet


def test_swagger_2_versioned_base_path_is_a_candidate(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{RES}/swagger.yml": """\
                swagger: "2.0"
                info:
                  title: Orders API
                basePath: /api/v1
                paths:
                  /orders: {}
            """
        },
    )
    c = run(repo)["swagger.yml"]
    assert "spec: Swagger 2.0" in c.snippet
    assert "signal: versioned base path: /api/v1" in c.snippet


def test_versioned_proto_package_with_a_service_is_a_candidate(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{PROTO}/orders.proto": """\
                syntax = "proto3";

                package shop.orders.v1;

                service OrderService {
                  rpc GetOrder (GetOrderRequest) returns (Order);
                  rpc ListOrders (ListOrdersRequest) returns (ListOrdersResponse);
                }
            """
        },
    )
    [c] = detect(repo, "demo", COMMIT)
    assert c.file == "src/main/proto/shop/v1/orders.proto"
    assert c.unit == Unit.FILE
    assert "spec: protobuf (proto3)" in c.snippet
    assert "signal: versioned package shop.orders.v1" in c.snippet
    assert "note: declares service OrderService with 2 rpc(s)" in c.snippet


def test_message_only_proto_imported_by_a_service_proto_is_noted_as_api(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{PROTO}/messages.proto": """\
                syntax = "proto3";
                package shop.v1beta1;
                message Order { int32 id = 1; }
            """,
            f"{PROTO}/service.proto": """\
                syntax = "proto3";
                package shop.v1beta1;
                import "shop/v1/messages.proto";
                service OrderService { rpc GetOrder (Order) returns (Order); }
            """,
        },
    )
    c = run(repo)["messages.proto"]
    assert "signal: versioned package shop.v1beta1" in c.snippet
    importer = f"{PROTO}/service.proto"  # relative to the repo root
    assert f"note: no service of its own; imported by service proto {importer}" in c.snippet


def test_message_only_proto_nobody_imports_is_flagged_as_maybe_an_event(tmp_path):
    # Still a candidate: whether it is an event schema is left to Claude.
    repo = write(
        tmp_path,
        {
            f"{PROTO}/events.proto": """\
                syntax = "proto3";
                package shop.events.v1;
                message OrderPlaced { int32 order_id = 1; }
            """
        },
    )
    c = run(repo)["events.proto"]
    assert "signal: versioned package shop.events.v1" in c.snippet
    assert "it belongs to event-schema-versioning, not versioned-api" in c.snippet


def test_build_time_info_version_is_noted(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{RES}/openapi.yaml": """\
                openapi: 3.0.3
                info:
                  title: Orders API
                  version: ${project.version}
            """
        },
    )
    c = run(repo)["openapi.yaml"]
    assert "signal: info.version ${project.version}" in c.snippet
    assert "note: info.version is filled at build time" in c.snippet


# ------------------------------------------------------- what doesn't count


def test_spec_with_no_version_and_no_versioned_paths_is_not_a_candidate(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{RES}/openapi.yaml": """\
                openapi: 3.0.3
                info:
                  title: Orders API
                servers:
                  - url: https://orders.example.com/api
                paths:
                  /orders: {}
            """
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_maven_pom_version_is_not_a_candidate(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{SVC}/pom.xml": """\
                <project>
                  <groupId>shop</groupId>
                  <artifactId>orders</artifactId>
                  <version>1.2.0</version>
                </project>
            """
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_actuator_info_version_in_application_yml_is_not_a_candidate(tmp_path):
    # Spring Boot's /actuator/info block looks like `info.version` but is not a spec.
    repo = write(
        tmp_path,
        {
            f"{RES}/application.yml": """\
                spring:
                  application:
                    name: orders-service
                info:
                  version: 1.2.0
                springdoc:
                  swagger-ui:
                    path: /v1/docs
            """
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_spec_under_src_test_is_skipped(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{SVC}/src/test/resources/openapi.yaml": """\
                openapi: 3.0.3
                info: { title: Fake API, version: 1.0.0 }
                paths:
                  /v1/orders: {}
            """
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_proto_without_a_versioned_package_is_not_a_candidate(tmp_path):
    # A version in the folder (shop/v1) is not enough; the package must carry it.
    repo = write(
        tmp_path,
        {
            f"{PROTO}/orders.proto": """\
                syntax = "proto3";
                package shop.orders;
                service OrderService { rpc GetOrder (Req) returns (Res); }
            """
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_versioned_package_in_a_comment_is_not_read(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{PROTO}/orders.proto": """\
                syntax = "proto3";
                // package shop.orders.v1;
                /* package shop.orders.v2; */
                package shop.orders;
            """
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_spec_that_is_not_valid_yaml_is_not_a_candidate(tmp_path):
    repo = write(
        tmp_path,
        {f"{RES}/openapi.yaml": "openapi: 3.0.3\ninfo: [title: Orders\n  version: 1.0.0\n"},
    )
    assert detect(repo, "demo", COMMIT) == []


# ------------------------------------------------------------ output format


def test_snippet_of_a_minified_json_spec_stays_within_the_limit(tmp_path):
    paths = {f"/v1/orders/{i}": {"get": {"summary": "x" * 50}} for i in range(200)}
    spec = {"openapi": "3.0.1", "info": {"title": "Orders", "version": "1"}, "paths": paths}
    repo = write(tmp_path, {f"{RES}/openapi.json": json.dumps(spec)})  # one huge line
    [c] = detect(repo, "demo", COMMIT)
    assert len(c.snippet) <= SNIPPET_MAX_CHARS
    assert "signal: versioned paths (200 of 200): /v1/orders/0, /v1/orders/1" in c.snippet
    assert "+197 more" in c.snippet
    assert c.snippet.endswith(" [...]")  # the long line is cut, not dropped


def test_main_prints_json_lines(tmp_path, capsys):
    repo = write(
        tmp_path,
        {
            f"{RES}/openapi.yaml": "openapi: 3.0.3\ninfo: { title: A, version: 1.0.0 }\n",
            f"{PROTO}/orders.proto": 'syntax = "proto3";\npackage shop.v1;\n',
        },
    )
    assert main([str(repo), "--repo-name", "demo", "--commit", COMMIT]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    for line in lines:  # one candidate per line, as the scoring script reads them
        c = Candidate.from_json(line)
        assert c.to_dict() == json.loads(line)
        assert c.unit == Unit.FILE
