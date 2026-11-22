"""event-schema-versioning rule, on small fake repos built in tmp_path (offline, no targets/)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from tc_detector.contracts.candidate import SNIPPET_MAX_CHARS, Candidate, Category, Unit
from tc_detector.rules.contracts.event_schema_versioning import PATTERN, RULE_ID, detect, main

COMMIT = "0" * 40
SVC = "shop-visits"  # service folder; named visits-service by its application.yml
API = "shop-api"  # second service folder; no app name, so `api` (folder minus `shop-`)
APP_YML = f"{SVC}/src/main/resources/application.yml"
APP_NAME = "spring:\n  application:\n    name: visits-service\n"

# The GUIDELINES positive example, word for word.
VISIT_CREATED = """\
    { "type": "record", "name": "VisitCreated", "namespace": "petclinic.events.v1",
      "fields": [ { "name": "petId", "type": "int" },
                  { "name": "note", "type": ["null", "string"], "default": null } ] }
"""
EVENT_PROTO = """\
    syntax = "proto3";
    package petclinic.events.v1;

    message VisitCreated {
      int32 pet_id = 1;
      string note = 2;
      reserved 3;
    }
"""
API_PROTO = """\
    syntax = "proto3";
    package shop.api.v1;
    import "shop/api/v1/common.proto";

    service OwnerService {
      rpc GetOwner (GetOwnerRequest) returns (shop.api.v1.Owner);
      rpc ListOwners (ListOwnersRequest) returns (stream shop.api.v1.Owner);
    }
    message GetOwnerRequest { int32 id = 1; }
    message ListOwnersRequest { string last_name = 1; }
"""


def write(repo: Path, files: dict[str, str]) -> Path:
    """Create a fake repo with two services plus `files` ({relative path: content})."""
    base = {
        f"{SVC}/pom.xml": "<project/>\n",
        APP_YML: APP_NAME,
        f"{API}/pom.xml": "<project/>\n",
    }
    for rel, content in {**base, **files}.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
    return repo


def run(repo: Path) -> dict[str, Candidate]:
    """Candidates keyed by file name, e.g. "VisitCreated.avsc"."""
    return {Path(c.file).name: c for c in detect(repo, "demo", COMMIT)}


# ------------------------------------------------------------- what counts


def test_guidelines_avro_example_is_a_file_candidate(tmp_path):
    repo = write(tmp_path, {f"{SVC}/src/main/avro/VisitCreated.avsc": VISIT_CREATED})
    [c] = detect(repo, "demo", COMMIT)
    assert c.file == "src/main/avro/VisitCreated.avsc"  # relative to the service root
    assert c.service == "visits-service"  # from spring.application.name
    assert (c.unit, c.line_start, c.line_end) == (Unit.FILE, None, None)
    assert (c.pattern, c.category, c.rule_id) == (PATTERN, Category.MODULARITY, RULE_ID)
    assert c.rule_id.startswith(c.category)
    assert c.id == f"demo:visits-service:{c.file}:file:event-schema-versioning"
    assert "schema: Avro record petclinic.events.v1.VisitCreated" in c.snippet
    assert "signal: version in namespace: petclinic.events.v1" in c.snippet
    assert "signal: fields with defaults (1 of 2): note" in c.snippet
    assert '"namespace": "petclinic.events.v1",' in c.snippet  # source is shown


def test_nested_record_inherits_namespace_and_its_defaults_count(tmp_path):
    schema = """\
        {"type": "record", "name": "VisitCreatedV2", "namespace": "petclinic.events",
         "fields": [
           {"name": "vet", "type": ["null", {"type": "record", "name": "VetRef",
             "fields": [{"name": "id", "type": "int"},
                        {"name": "speciality", "type": "string", "default": "none"}]}],
            "default": null}]}
    """
    repo = write(tmp_path, {f"{SVC}/src/main/resources/avro/visit-created-v2.avsc": schema})
    c = run(repo)["visit-created-v2.avsc"]
    assert "schema: Avro record petclinic.events.VisitCreatedV2 (+1 more: VetRef)" in c.snippet
    assert "version in namespace" not in c.snippet  # petclinic.events has no version part
    assert "signal: version in type name: VisitCreatedV2" in c.snippet
    assert "signal: version in file name: visit-created-v2" in c.snippet
    assert "signal: fields with defaults (2 of 3): vet, speciality" in c.snippet


def test_event_proto_with_versioned_package_is_a_candidate(tmp_path):
    repo = write(tmp_path, {f"{SVC}/src/main/proto/visit_events.proto": EVENT_PROTO})
    [c] = detect(repo, "demo", COMMIT)
    assert c.file == "src/main/proto/visit_events.proto"
    assert "schema: protobuf (proto3), package petclinic.events.v1, messages VisitCreated" in (
        c.snippet
    )
    assert "signal: versioned package petclinic.events.v1" in c.snippet
    assert "signal: reserved: 3" in c.snippet
    assert "note: no service or rpc, and no proto with a service imports it: possible event" in (
        c.snippet
    )


def test_schema_with_no_evolution_sign_is_still_a_candidate(tmp_path):
    # Owner decision: the schema file alone is enough; the snippet says there are no signs.
    proto = 'syntax = "proto3";\npackage shop.events;\nmessage OrderPlaced { int32 id = 1; }\n'
    avro = '{"type": "record", "name": "OrderPaid", "fields": [{"name": "id", "type": "int"}]}'
    repo = write(
        tmp_path,
        {f"{SVC}/src/main/proto/orders.proto": proto, f"{SVC}/src/main/avro/paid.avsc": avro},
    )
    found = run(repo)
    assert set(found) == {"orders.proto", "paid.avsc"}
    for c in found.values():
        assert "signal: none (schema file only)" in c.snippet


def test_deprecated_proto_field_is_a_signal(tmp_path):
    proto = """\
        syntax = "proto3";
        package shop.events;
        message OrderPlaced {
          int32 id = 1;
          string coupon = 2 [deprecated = true];
          bool reserved = 3;
        }
    """
    repo = write(tmp_path, {f"{SVC}/src/main/proto/orders.proto": proto})
    [c] = detect(repo, "demo", COMMIT)
    assert "signal: deprecated fields: coupon" in c.snippet
    assert "signal: reserved" not in c.snippet  # a field named `reserved` is not `reserved N;`


# ----------------------------------------------------- left to Claude (noted)


def test_rpc_api_proto_is_a_candidate_with_a_versioned_api_note(tmp_path):
    # Owner decision: emit it and let Claude send pure APIs to versioned-api.
    repo = write(tmp_path, {f"{API}/src/main/proto/shop/api/v1/owners.proto": API_PROTO})
    [c] = detect(repo, "demo", COMMIT)
    assert (c.service, c.file) == ("api", "src/main/proto/shop/api/v1/owners.proto")
    assert (
        "note: declares service OwnerService with 2 rpc(s): if it only defines "
        "request/response APIs, it belongs to versioned-api, not event-schema-versioning"
    ) in c.snippet


def test_proto_imported_by_an_rpc_proto_is_noted(tmp_path):
    common = 'syntax = "proto3";\npackage shop.api.v1;\nmessage Owner { int32 id = 1; }\n'
    repo = write(
        tmp_path,
        {
            f"{API}/src/main/proto/shop/api/v1/owners.proto": API_PROTO,
            f"{API}/src/main/proto/shop/api/v1/common.proto": common,
        },
    )
    c = run(repo)["common.proto"]
    assert (
        "note: no service of its own; imported by service proto "
        "shop-api/src/main/proto/shop/api/v1/owners.proto"
    ) in c.snippet


def test_service_in_a_comment_does_not_make_a_proto_an_api(tmp_path):
    proto = EVENT_PROTO + "// service Old { rpc Get (A) returns (B); }\n"
    repo = write(tmp_path, {f"{SVC}/src/main/proto/visit_events.proto": proto})
    [c] = detect(repo, "demo", COMMIT)
    assert "possible event schema" in c.snippet
    assert "declares service" not in c.snippet


# ------------------------------------------------------------------ registry


def test_registry_in_the_same_service_is_a_signal_on_the_schema(tmp_path):
    yml = APP_NAME + (
        "  kafka:\n"
        "    producer:\n"
        "      value-serializer: io.confluent.kafka.serializers.KafkaAvroSerializer\n"
        "    properties:\n"
        "      schema.registry.url: http://registry:8081\n"
    )
    repo = write(tmp_path, {APP_YML: yml, f"{SVC}/src/main/avro/VisitCreated.avsc": VISIT_CREATED})
    [c] = detect(repo, "demo", COMMIT)  # application.yml itself is never a candidate
    assert c.file == "src/main/avro/VisitCreated.avsc"
    assert (
        "signal: schema registry configured in this service: src/main/resources/"
        "application.yml:6 `value-serializer: io.confluent.kafka.serializers."
        "KafkaAvroSerializer`, src/main/resources/application.yml:8 `schema.registry.url:"
    ) in c.snippet


def test_registry_in_another_service_is_named_on_the_schema(tmp_path):
    props = "spring.cloud.schema-registry-client.endpoint=http://registry:8990\n"
    repo = write(
        tmp_path,
        {
            f"{API}/src/main/resources/application.properties": props,
            f"{SVC}/src/main/avro/VisitCreated.avsc": VISIT_CREATED,
        },
    )
    [c] = detect(repo, "demo", COMMIT)
    assert "signal: schema registry configured in other service(s): api" in c.snippet


def test_registry_alone_with_no_schema_file_is_not_a_candidate(tmp_path):
    yml = APP_NAME + "  kafka:\n    properties:\n      schema.registry.url: http://r:8081\n"
    repo = write(tmp_path, {APP_YML: yml})
    assert detect(repo, "demo", COMMIT) == []


def test_commented_out_registry_is_ignored(tmp_path):
    yml = APP_NAME + "#  schema.registry.url: http://registry:8081\n"
    repo = write(tmp_path, {APP_YML: yml, f"{SVC}/src/main/avro/VisitCreated.avsc": VISIT_CREATED})
    [c] = detect(repo, "demo", COMMIT)
    assert "schema registry" not in c.snippet


# ------------------------------------------------------- what doesn't count


def test_plain_java_event_class_with_no_schema_is_not_a_candidate(tmp_path):
    # The GUIDELINES negative example: sent as plain JSON, no schema file.
    repo = write(
        tmp_path,
        {
            f"{SVC}/src/main/java/shop/events/VisitCreated.java": (
                "public class VisitCreated { public int petId; public String note; }\n"
            )
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_test_code_is_skipped(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{SVC}/src/test/resources/avro/VisitCreated.avsc": VISIT_CREATED,
            f"{SVC}/src/test/proto/visit_events.proto": EVENT_PROTO,
        },
    )
    assert detect(repo, "demo", COMMIT) == []


def test_build_output_is_skipped(tmp_path):
    repo = write(tmp_path, {f"{SVC}/target/classes/avro/VisitCreated.avsc": VISIT_CREATED})
    assert detect(repo, "demo", COMMIT) == []


def test_avsc_that_is_not_valid_json_is_skipped(tmp_path):
    repo = write(
        tmp_path,
        {
            f"{SVC}/src/main/avro/broken.avsc": '{"type": "record", "name": "Broken",\n',
            f"{SVC}/src/main/avro/numbers.avsc": "[1, 2, 3]\n",  # valid JSON, not a schema
        },
    )
    assert detect(repo, "demo", COMMIT) == []


# ---------------------------------------------------------------- output


def test_repo_name_defaults_to_folder_name(tmp_path):
    repo = write(
        tmp_path / "spring-petclinic-microservices",
        {f"{SVC}/src/main/avro/VisitCreated.avsc": VISIT_CREATED},
    )
    [c] = detect(repo, commit=COMMIT)
    assert c.repo == "spring-petclinic-microservices"


def test_snippet_stays_within_the_limit(tmp_path):
    fields = ",\n".join(
        f'  {{"name": "field{i:03d}", "type": "string", "doc": "{"x" * 150}"}}' for i in range(60)
    )
    schema = f'{{"type": "record", "name": "Huge", "fields": [\n{fields}\n]}}\n'
    repo = write(tmp_path, {f"{SVC}/src/main/avro/Huge.avsc": schema})
    [c] = detect(repo, "demo", COMMIT)
    assert len(c.snippet) <= SNIPPET_MAX_CHARS
    assert c.snippet.endswith("[... truncated]")


def test_main_prints_json_lines(tmp_path, capsys):
    repo = write(
        tmp_path,
        {
            f"{SVC}/src/main/avro/VisitCreated.avsc": VISIT_CREATED,
            f"{SVC}/src/main/proto/visit_events.proto": EVENT_PROTO,
        },
    )
    assert main([str(repo), "--repo-name", "demo", "--commit", COMMIT]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    for line in lines:  # one candidate per line, as the scoring script reads them
        c = Candidate.from_json(line)
        assert c.to_dict() == json.loads(line)
        assert c.unit == Unit.FILE
