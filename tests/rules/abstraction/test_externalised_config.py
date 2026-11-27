"""Externalised-config rule, on small fake repos built in tmp_path (offline, no targets/)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tc_detector.contracts.candidate import SNIPPET_MAX_CHARS, Candidate, Category, Unit
from tc_detector.rules.abstraction.externalised_config import (
    PATTERN,
    RULE_ID,
    detect,
    is_config_server_import,
    split_imports,
)

COMMIT = "0" * 40
RES = "src/main/resources"


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


def service(folder: str, config: dict[str, str], *artifacts: str) -> dict[str, str]:
    """One service folder: a pom plus config files under src/main/resources."""
    files = {f"{folder}/pom.xml": pom(*(artifacts or ("spring-boot-starter-web",)))}
    files.update({f"{folder}/{RES}/{name}": text for name, text in config.items()})
    return files


def app_yml(name: str, extra: str = "") -> str:
    return f"spring:\n  application:\n    name: {name}\n{extra}"


# A second, plain service, so every fake repo has more than one service folder.
OTHER = service("other", {"application.yml": app_yml("other-service")})


def run(repo: Path) -> dict[str, Candidate]:
    return {c.service: c for c in detect(repo, "demo", COMMIT)}


def one(tmp_path: Path, config: dict[str, str], *artifacts: str) -> dict[str, Candidate]:
    return run(write(tmp_path, {**service("svc", config, *artifacts), **OTHER}))


# ------------------------------------------------------------- import signal


def test_configserver_import(tmp_path):
    found = one(tmp_path, {"application.yml": app_yml("svc", IMPORT.format("configserver:"))})
    assert set(found) == {"svc"}
    assert "spring.config.import configserver:http://cfg:8888 at" in found["svc"].snippet


IMPORT = "  config:\n    import: {}http://cfg:8888\n"


def test_optional_prefix_still_counts(tmp_path):
    """Guideline: the `optional:` prefix still counts."""
    found = one(
        tmp_path, {"application.yml": app_yml("svc", IMPORT.format("optional:configserver:"))}
    )
    assert set(found) == {"svc"}
    assert f"{RES}/application.yml:5" in found["svc"].snippet


def test_import_in_properties_file(tmp_path):
    props = "spring.application.name=svc\nspring.config.import=optional:configserver:\n"
    found = one(tmp_path, {"application.properties": props})
    assert set(found) == {"svc"}
    assert f"{RES}/application.properties:2" in found["svc"].snippet


def test_indexed_import_in_properties_file(tmp_path):
    props = "spring.application.name=svc\nspring.config.import[0]: configserver:http://cfg\n"
    assert set(one(tmp_path, {"application.properties": props})) == {"svc"}


def test_import_in_profile_variant_file(tmp_path):
    config = {
        "application.yml": app_yml("svc"),
        "application-docker.yml": "spring:\n  config:\n    import: configserver:http://cfg\n",
    }
    found = one(tmp_path, config)
    assert set(found) == {"svc"}
    assert f"{RES}/application-docker.yml:3" in found["svc"].snippet


def test_import_in_profile_document_of_a_multi_document_file(tmp_path):
    yml = app_yml("svc") + "---\nspring:\n  config:\n    activate:\n      on-profile: docker\n"
    yml += "    import: configserver:http://config-server:8888\n"
    found = one(tmp_path, {"application.yml": yml})
    assert f"{RES}/application.yml:9" in found["svc"].snippet


def test_import_as_a_yaml_list_and_dotted_key(tmp_path):
    yml = app_yml("svc", "  config.import:\n    - optional:file:./x.yml\n    - 'configserver:'\n")
    found = one(tmp_path, {"application.yml": yml})
    assert set(found) == {"svc"}
    assert f"spring.config.import configserver: at {RES}/application.yml:6" in found["svc"].snippet
    assert "file:" not in found["svc"].snippet


def test_mixed_import_list_like_genai_service(tmp_path):
    """PetClinic genai-service: a configserver entry next to a classpath file."""
    value = "optional:configserver:${CONFIG_SERVER_URL:http://localhost:8888/},"
    value += "optional:classpath:/creds.yaml"
    found = one(tmp_path, {"application.yml": app_yml("svc", f"  config:\n    import: {value}\n")})
    assert set(found) == {"svc"}
    snippet = found["svc"].snippet
    assert "optional:configserver:${CONFIG_SERVER_URL:http://localhost:8888/}" in snippet
    assert "creds.yaml" not in snippet


def test_classpath_import_only_is_not_external(tmp_path):
    """Guideline edge case: optional:classpath:/creds.yaml is a local file."""
    yml = app_yml("svc", "  config:\n    import: optional:classpath:/creds.yaml\n")
    assert one(tmp_path, {"application.yml": yml}) == {}


def test_file_import_only_is_not_a_config_server(tmp_path):
    yml = app_yml("svc", "  config:\n    import: optional:file:./config/\n")
    assert one(tmp_path, {"application.yml": yml}) == {}


def test_env_var_placeholders_alone_do_not_count(tmp_path):
    """Guideline edge case: ${ENV_VAR} placeholders alone don't make a service positive."""
    yml = app_yml(
        "svc",
        "  ai:\n    openai:\n      api-key: ${OPENAI_API_KEY}\n"
        "  datasource:\n    url: ${DB_URL:jdbc:h2:mem:x}\n",
    )
    assert one(tmp_path, {"application.yml": yml}) == {}


def test_import_that_is_only_a_placeholder_does_not_count(tmp_path):
    yml = app_yml("svc", "  config:\n    import: ${CONFIG_IMPORT}\n")
    assert one(tmp_path, {"application.yml": yml}) == {}


def test_commented_out_import_does_not_count(tmp_path):
    props = "spring.application.name=svc\n# spring.config.import=configserver:\n"
    yml = app_yml("svc", "  # config:\n  #   import: configserver:\n")
    assert one(tmp_path / "p", {"application.properties": props}) == {}
    assert one(tmp_path / "y", {"application.yml": yml}) == {}


def test_import_under_another_prefix_does_not_count(tmp_path):
    yml = app_yml("svc", "  other:\n    config:\n      import: configserver:\n")
    assert one(tmp_path, {"application.yml": yml}) == {}


def test_import_in_test_resources_is_ignored(tmp_path):
    files = {
        **service("svc", {"application.yml": app_yml("svc")}),
        "svc/src/test/resources/application.yml": "spring:\n  config:\n    import: configserver:\n",
        **OTHER,
    }
    assert run(write(tmp_path, files)) == {}


def test_invalid_yaml_is_skipped(tmp_path):
    assert one(tmp_path, {"application.yml": "spring: [unclosed\n"}) == {}


# ---------------------------------------------------------- bootstrap signal


def test_bootstrap_yml_config_uri(tmp_path):
    """Pre-2.4 equivalent of the configserver import (not exercised by PetClinic)."""
    config = {
        "application.yml": app_yml("svc"),
        "bootstrap.yml": "spring:\n  cloud:\n    config:\n      uri: http://cfg:8888\n",
    }
    found = one(tmp_path, config)
    assert set(found) == {"svc"}
    assert f"bootstrap spring.cloud.config.uri http://cfg:8888 at {RES}/bootstrap.yml:4" in (
        found["svc"].snippet
    )


def test_bootstrap_properties_config_uri(tmp_path):
    config = {
        "application.yml": app_yml("svc"),
        "bootstrap.properties": "spring.cloud.config.uri=http://cfg:8888\n",
    }
    found = one(tmp_path, config)
    assert f"{RES}/bootstrap.properties:1" in found["svc"].snippet


def test_bootstrap_profile_variant(tmp_path):
    config = {
        "application.yml": app_yml("svc"),
        "bootstrap-docker.yml": "spring.cloud.config.uri: http://config-server:8888\n",
    }
    assert set(one(tmp_path, config)) == {"svc"}


def test_config_uri_in_application_file_is_not_the_bootstrap_signal(tmp_path):
    """Since Boot 2.4, spring.cloud.config.uri in application.yml loads nothing by itself."""
    yml = app_yml("svc", "  cloud:\n    config:\n      uri: http://cfg:8888\n")
    assert one(tmp_path, {"application.yml": yml}) == {}


def test_empty_bootstrap_config_uri_does_not_count(tmp_path):
    config = {
        "application.yml": app_yml("svc"),
        "bootstrap.properties": "spring.cloud.config.uri=\n",
    }
    assert one(tmp_path, config) == {}


def test_bootstrap_without_config_uri_does_not_count(tmp_path):
    config = {"bootstrap.yml": app_yml("svc", "  cloud:\n    config:\n      name: svc\n")}
    assert one(tmp_path, config) == {}


# ---------------------------------------------------------- config server


CONFIG_SERVER_YML = app_yml(
    "config-server",
    "  cloud:\n    config:\n      server:\n        git:\n"
    "          uri: https://github.com/spring-petclinic/spring-petclinic-microservices-config\n"
    "server:\n  port: 8888\n",
)


def test_config_server_itself_is_not_a_candidate(tmp_path):
    """Guideline negative: config-server serves config; its own config is local."""
    files = {
        **service("cfg", {"application.yml": CONFIG_SERVER_YML}, "spring-cloud-config-server"),
        **OTHER,
    }
    assert run(write(tmp_path, files)) == {}


def test_config_server_git_uri_in_bootstrap_is_not_the_bootstrap_signal(tmp_path):
    files = {
        **service("cfg", {"bootstrap.yml": CONFIG_SERVER_YML}, "spring-cloud-config-server"),
        **OTHER,
    }
    assert run(write(tmp_path, files)) == {}


# ------------------------------------------------------- client dependency


def test_client_dependency_alone_is_not_a_signal(tmp_path):
    found = one(tmp_path, {"application.yml": app_yml("svc")}, "spring-cloud-starter-config")
    assert found == {}


def test_client_dependency_is_added_to_a_qualifying_service(tmp_path):
    yml = app_yml("svc", IMPORT.format("optional:configserver:"))
    found = one(tmp_path, {"application.yml": yml}, "spring-cloud-starter-config")
    assert "supporting: config client dependency spring-cloud-starter-config at pom.xml:3" in (
        found["svc"].snippet
    )


def test_config_server_dependency_is_not_client_evidence(tmp_path):
    yml = app_yml("svc", IMPORT.format("configserver:"))
    found = one(tmp_path, {"application.yml": yml}, "spring-cloud-config-server")
    assert "supporting" not in found["svc"].snippet


# ------------------------------------------------------- helpers


@pytest.mark.parametrize(
    ("value", "parts"),
    [
        ("configserver:", ["configserver:"]),
        (" a , b ", ["a", "b"]),
        ("optional:configserver:${U:http://h:1/},optional:classpath:/c.yaml", 2),
        ("configserver:${A:${B:x,y}},file:z", ["configserver:${A:${B:x,y}}", "file:z"]),
        ("", []),
    ],
)
def test_split_imports(value, parts):
    got = split_imports(value)
    assert len(got) == parts if isinstance(parts, int) else got == parts


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("configserver:", True),
        ("configserver:http://cfg:8888", True),
        ("optional:configserver:http://cfg", True),
        ("optional:classpath:/creds.yaml", False),
        ("classpath:configserver.yml", False),
        ("file:./configserver/", False),
        ("${CONFIG_IMPORT}", False),
    ],
)
def test_is_config_server_import(entry, expected):
    assert is_config_server_import(entry) is expected


# ------------------------------------------------- guideline examples, shape


def petclinic_like(tmp_path: Path) -> Path:
    """The guideline's examples: 7 services importing from config-server, plus config-server."""
    imp = (
        "  config:\n    import: optional:configserver:${CONFIG_SERVER_URL:http://localhost:8888/}\n"
    )
    files: dict[str, str] = {}
    for name in ("admin-server", "api-gateway", "customers-service", "discovery-server"):
        files |= service(f"spring-petclinic-{name}", {"application.yml": app_yml(name, imp)})
    for name in ("vets-service", "visits-service"):
        files |= service(f"spring-petclinic-{name}", {"application.yml": app_yml(name, imp)})
    genai = imp.rstrip("\n") + ",optional:classpath:/creds.yaml\n"
    genai += "  ai:\n    openai:\n      api-key: ${OPENAI_API_KEY:demo}\n"
    files |= service(
        "spring-petclinic-genai-service", {"application.yml": app_yml("genai-service", genai)}
    )
    files |= service(
        "spring-petclinic-config-server",
        {"application.yml": CONFIG_SERVER_YML},
        "spring-cloud-config-server",
    )
    return write(tmp_path, files)


def test_guideline_examples(tmp_path):
    found = run(petclinic_like(tmp_path))
    assert set(found) == {
        "admin-server",
        "api-gateway",
        "customers-service",
        "discovery-server",
        "genai-service",
        "vets-service",
        "visits-service",
    }


def test_candidates_pass_the_candidate_checks(tmp_path):
    for c in detect(petclinic_like(tmp_path), "demo", COMMIT):
        assert Candidate.from_json(c.to_json()) == c
        assert c.id == f"demo:{c.service}:-:service:externalised-config"
        assert (c.unit, c.pattern, c.category, c.rule_id) == (
            Unit.SERVICE,
            PATTERN,
            Category.CONFIGURABILITY,
            RULE_ID,
        )
        assert (c.file, c.line_start, c.line_end) == (None, None, None)
        assert c.commit == COMMIT
        assert c.snippet.startswith(f"externalised-config candidate: service {c.service}\n")


def test_pattern_and_rule_id_strings():
    assert PATTERN == "externalised-config"
    assert RULE_ID == "configurability-externalised-config-01"


def test_snippet_stays_within_the_limit(tmp_path):
    lines = "".join(f"spring.config.import[{i}]=configserver:http://h{i}\n" for i in range(200))
    found = one(tmp_path, {"application.properties": "spring.application.name=svc\n" + lines})
    snippet = found["svc"].snippet
    assert len(snippet) <= SNIPPET_MAX_CHARS
    assert snippet.endswith("[... truncated]")
