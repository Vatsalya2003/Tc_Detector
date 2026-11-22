"""event-schema-versioning detection. Owner: Abhi (B).

Pattern `event-schema-versioning`, category `modularity`, matching unit `file`. One
candidate per event schema file, with `line_start`/`line_end` None. See
ground_truth/GUIDELINES.md, `event-schema-versioning`.

Schema files looked at (never test code or build output; see common.py):
  Avro      a .avsc file that is valid JSON and holds a schema (an object with a `type`,
            or a list of them)
  Protobuf  a .proto file

Counts (owner decision: the schema file alone is enough; the evolution signs below go in
the snippet as evidence, and the snippet says when there are none):
  Avro      fields with a `default` (readers of old data fill them in); a version part in
            the namespace (`petclinic.events.v1`), a record/enum name (`VisitCreatedV2`)
            or the file name (`visit-created-v1.avsc`)
  Protobuf  a version part in the `package` (`petclinic.events.v1`); `reserved` field
            numbers or names (retired fields can't be reused); fields marked
            `deprecated = true`. Every proto field has a number, so a proto is evolvable
            by design; which numbers are new can't be told without history.
  Registry  (owner decision: a signal, never a candidate) a schema registry setting in an
            application*/bootstrap* .yml/.yaml/.properties file: a `schema.registry.url`
            or `schema-registry` key, a Confluent Avro/Protobuf/JSON-Schema serializer,
            Spring Cloud's schema-registry-client, or Apicurio. Settings in the schema's
            own service are shown first, then those in other services (a shared schema
            module rarely holds the Kafka config).

Doesn't count:
  - a Java event class sent as plain JSON, with no schema file (GUIDELINES negative):
    Java is never read;
  - a .avsc that is not valid JSON (avro tools can't read it either);
  - a registry setting with no schema file in the repo: config files are never candidates.

Left to Claude, noted in the snippet (owner decision: emit, don't skip):
  - proto for events or for an API? A .proto used only for request/response APIs belongs
    to versioned-api (GUIDELINES edge case). As in versioned_api.py, the snippet says
    whether the file declares a `service` with rpcs or is imported by a proto that does.
    If neither, it notes that the file is a possible event schema.

Known limits: Avro IDL (.avdl), Avro protocols (.avpr) and JSON Schema files are not read;
GUIDELINES names only .avsc and .proto.

Run by hand (prints one candidate JSON per line):
    uv run python -m tc_detector.rules.contracts.event_schema_versioning \\
        targets/spring-petclinic-microservices
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from tc_detector.contracts.candidate import Candidate, Category, Unit
from tc_detector.rules.contracts.common import (
    Service,
    find_services,
    head_commit,
    service_files,
    trim_snippet,
)

PATTERN = "event-schema-versioning"
CATEGORY = Category.MODULARITY
RULE_ID = "modularity-event-schema-versioning-01"

AVRO_NAMED_TYPES = {"record", "error", "enum", "fixed"}
CONFIG_SUFFIXES = (".yml", ".yaml", ".properties")
CONFIG_PREFIXES = ("application", "bootstrap")
SOURCE_LINES = 30  # head of the file shown in the snippet
SOURCE_LINE_CHARS = 200  # a minified .avsc is one huge line
SHOWN = 3  # list items shown before "+N more"

_VERSION_PART = re.compile(r"v\d+(?:[a-z]+\d*)*")  # one package part: v1, v1beta1, v1p1beta1
# A version at the end of a name: VisitCreatedV2, visit_created_v1, visit-created-v1.
_VERSION_SUFFIX = re.compile(r"(?:(?<=[a-z0-9])V|(?:^|(?<=[_.-]))[vV])\d+$")
# Same proto parsing as versioned_api.py, so both rules read a .proto the same way.
_PROTO_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)
_PROTO_SYNTAX = re.compile(r"^\s*syntax\s*=\s*[\"'](\w+)[\"']\s*;", re.MULTILINE)
_PROTO_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
_PROTO_SERVICE = re.compile(r"\bservice\s+(\w+)\s*\{")
_PROTO_RPC = re.compile(r"\brpc\s+\w+\s*\(")
_PROTO_IMPORT = re.compile(
    r"^\s*import\s+(?:public\s+|weak\s+)?[\"']([^\"']+)[\"']\s*;", re.MULTILINE
)
_PROTO_MESSAGE = re.compile(r"^\s*message\s+(\w+)\s*\{", re.MULTILINE)
_PROTO_RESERVED = re.compile(r"\breserved\s+([^;=]+);")  # not a field named `reserved`
_PROTO_DEPRECATED = re.compile(r"\b(\w+)\s*=\s*\d+\s*\[[^\]]*\bdeprecated\s*=\s*true\b")
# Registry settings, matched on a config line with comments removed.
_REGISTRY = re.compile(
    r"schema[._-]?registry|KafkaAvro(?:De)?Serializer|KafkaProtobuf(?:De)?Serializer"
    r"|KafkaJsonSchema(?:De)?Serializer|apicurio",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SchemaFile:
    """One schema file that is a candidate, and what to tell Claude about it."""

    rel: str  # path relative to the service root, with "/"
    kind: str  # "Avro record petclinic.events.v1.VisitCreated", "protobuf (proto3)"
    signals: list[str]
    notes: list[str]
    head: list[str]  # the first lines of the file, for the snippet
    more_lines: int  # lines left out of `head`


@dataclass(frozen=True)
class Proto:
    """One parsed .proto file (comments removed before reading it)."""

    path: Path
    rel: str  # relative to the service root
    repo_rel: str  # relative to the repo root, to match other protos' imports
    syntax: str | None
    package: str | None
    services: list[str]
    rpcs: int
    imports: list[str]
    messages: list[str]
    reserved: list[str]
    deprecated: list[str]


@dataclass(frozen=True)
class RegistryHit:
    """One schema-registry setting in a service's config."""

    service: Service
    rel: str  # config file, relative to its service root
    line: int
    text: str


# ------------------------------------------------------------------- helpers


def _shown(items: list[str]) -> str:
    more = len(items) - SHOWN
    return ", ".join(items[:SHOWN]) + (f" +{more} more" if more > 0 else "")


def _read(path: Path) -> str:
    # utf-8-sig drops a byte-order mark, which json.loads would reject.
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _head(text: str) -> tuple[list[str], int]:
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    head = [
        line if len(line) <= SOURCE_LINE_CHARS else line[:SOURCE_LINE_CHARS] + " [...]"
        for line in lines[:SOURCE_LINES]
    ]
    return head, max(len(lines) - SOURCE_LINES, 0)


def _versioned_package(name: str | None) -> bool:
    return bool(name) and any(_VERSION_PART.fullmatch(part) for part in name.split("."))


# ----------------------------------------------------------------------- Avro


def _avro_type(schema: dict) -> str | None:
    t = schema.get("type")
    return t if isinstance(t, str) else None


def _avro_fields(schema: dict) -> list[dict]:
    fields = schema.get("fields")
    return [f for f in fields if isinstance(f, dict)] if isinstance(fields, list) else []


def _avro_named(schema: object) -> Iterator[tuple[str, dict]]:
    """(full name, schema) of every named type (record, enum, fixed), nested ones too.

    A nested type with no namespace of its own takes the nearest enclosing one (Avro spec).
    """
    stack: list[tuple[object, str | None]] = [(schema, None)]
    while stack:
        s, ns = stack.pop()
        if isinstance(s, list):
            stack.extend((x, ns) for x in reversed(s))
            continue
        if not isinstance(s, dict):
            continue
        name = s.get("name")
        if _avro_type(s) in AVRO_NAMED_TYPES and isinstance(name, str):
            if "." in name:
                ns, name = name.rsplit(".", 1)
            elif isinstance(s.get("namespace"), str):
                ns = s["namespace"] or None  # "" resets to no namespace
            yield (f"{ns}.{name}" if ns else name), s
        children = [f.get("type") for f in _avro_fields(s)]
        children += [s.get(k) for k in ("type", "items", "values")]
        stack.extend((c, ns) for c in reversed(children) if isinstance(c, dict | list))


def avro_signals(schema: object, file_stem: str) -> tuple[str, list[str]]:
    """What the schema is ("Avro record a.b.C") and its evolution signs."""
    named = list(_avro_named(schema))
    if named:
        (first, top), rest = named[0], [n.rsplit(".", 1)[-1] for n, _ in named[1:]]
        kind = f"Avro {_avro_type(top)} {first}"
        if rest:
            kind += f" (+{len(rest)} more: {_shown(rest)})"
    else:
        kind = "Avro schema with no named type"
    signals = []
    namespaces = sorted({n.rsplit(".", 1)[0] for n, _ in named if "." in n})
    versioned_ns = [ns for ns in namespaces if _versioned_package(ns)]
    if versioned_ns:
        signals.append(f"version in namespace: {_shown(versioned_ns)}")
    short = [n.rsplit(".", 1)[-1] for n, _ in named]
    versioned_names = [n for n in short if _VERSION_SUFFIX.search(n)]
    if versioned_names:
        signals.append(f"version in type name: {_shown(versioned_names)}")
    if _VERSION_SUFFIX.search(file_stem):
        signals.append(f"version in file name: {file_stem}")
    fields = [f for _, s in named if _avro_type(s) in ("record", "error") for f in _avro_fields(s)]
    defaulted = [str(f.get("name")) for f in fields if "default" in f]
    if defaulted:
        signals.append(
            f"fields with defaults ({len(defaulted)} of {len(fields)}): {_shown(defaulted)}"
        )
    return kind, signals


def avro_schema(path: Path, service_root: Path) -> SchemaFile | None:
    """The .avsc as a candidate if it is valid JSON holding an Avro schema."""
    text = _read(path)
    try:
        schema = json.loads(text)
    except ValueError:
        return None
    is_schema = isinstance(schema, dict) and "type" in schema
    is_union = isinstance(schema, list) and any(isinstance(s, dict | str) for s in schema)
    if not (is_schema or is_union):
        return None
    kind, signals = avro_signals(schema, path.stem)
    head, more = _head(text)
    return SchemaFile(path.relative_to(service_root).as_posix(), kind, signals, [], head, more)


# ------------------------------------------------------------------- protobuf


def _parse_proto(path: Path, service_root: Path, repo: Path) -> Proto:
    # Comments become blank lines, so `// package a.v1;` is never read as code.
    code = _PROTO_COMMENT.sub(lambda m: "\n" * m.group().count("\n") or " ", _read(path))
    syntax = _PROTO_SYNTAX.search(code)
    package = _PROTO_PACKAGE.search(code)
    return Proto(
        path=path,
        rel=path.relative_to(service_root).as_posix(),
        repo_rel=path.relative_to(repo).as_posix(),
        syntax=syntax.group(1) if syntax else None,
        package=package.group(1) if package else None,
        services=_PROTO_SERVICE.findall(code),
        rpcs=len(_PROTO_RPC.findall(code)),
        imports=_PROTO_IMPORT.findall(code),
        messages=_PROTO_MESSAGE.findall(code),
        reserved=[" ".join(r.split()) for r in _PROTO_RESERVED.findall(code)],
        deprecated=_PROTO_DEPRECATED.findall(code),
    )


def _imports(importer: Proto, proto: Proto) -> bool:
    """Does `importer` import `proto`? Import paths are relative to a proto source root."""
    return any(proto.repo_rel == i or proto.repo_rel.endswith("/" + i) for i in importer.imports)


def proto_signals(proto: Proto) -> list[str]:
    signals = []
    if _versioned_package(proto.package):
        signals.append(f"versioned package {proto.package}")
    if proto.reserved:
        signals.append(f"reserved: {_shown(proto.reserved)}")
    if proto.deprecated:
        signals.append(f"deprecated fields: {_shown(proto.deprecated)}")
    return signals


def proto_notes(proto: Proto, all_protos: list[Proto]) -> list[str]:
    """The API-or-event note (the inverse of versioned_api.py's)."""
    if proto.services:
        return [
            f"declares service {', '.join(proto.services)} with {proto.rpcs} rpc(s): if it "
            "only defines request/response APIs, it belongs to versioned-api, not "
            "event-schema-versioning"
        ]
    importers = [p.repo_rel for p in all_protos if p.services and _imports(p, proto)]
    if importers:
        return [
            f"no service of its own; imported by service proto {_shown(importers)}: if it "
            "only carries request/response messages, it belongs to versioned-api, not "
            "event-schema-versioning"
        ]
    return ["no service or rpc, and no proto with a service imports it: possible event schema"]


def proto_schema(proto: Proto, all_protos: list[Proto]) -> SchemaFile:
    kind = f"protobuf ({proto.syntax})" if proto.syntax else "protobuf"
    if proto.package:
        kind += f", package {proto.package}"
    if proto.messages:
        kind += f", messages {_shown(proto.messages)}"
    head, more = _head(_read(proto.path))
    notes = proto_notes(proto, all_protos)
    return SchemaFile(proto.rel, kind, proto_signals(proto), notes, head, more)


# ------------------------------------------------------------------- registry


def registry_hits(service: Service, roots: list[Path]) -> list[RegistryHit]:
    """Schema-registry settings in this service's application*/bootstrap* config files."""
    hits = []
    for suffix in CONFIG_SUFFIXES:
        for path in service_files(service, roots, suffix):
            if not path.name.startswith(CONFIG_PREFIXES):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.split("\n"), start=1):
                code = line.strip()
                if not code or code.startswith(("#", "!")):
                    continue
                code = code.split(" #", 1)[0].strip()  # YAML end-of-line comment
                if _REGISTRY.search(code):
                    rel = path.relative_to(service.root).as_posix()
                    hits.append(RegistryHit(service, rel, number, code[:SOURCE_LINE_CHARS]))
    return hits


def registry_signal(service: Service, hits: list[RegistryHit]) -> str | None:
    """One snippet line on schema-registry settings, own service first."""
    own = [h for h in hits if h.service == service]
    if own:
        shown = _shown([f"{h.rel}:{h.line} `{h.text}`" for h in own])
        return f"schema registry configured in this service: {shown}"
    others = sorted({h.service.name for h in hits})
    if others:
        return f"schema registry configured in other service(s): {_shown(others)}"
    return None


# --------------------------------------------------------------------- output


def _snippet(service: str, schema: SchemaFile, registry: str | None) -> str:
    lines = [f"{PATTERN} candidate: service {service}, file {schema.rel}", f"schema: {schema.kind}"]
    signals = schema.signals + ([registry] if registry else [])
    lines += [f"signal: {s}" for s in signals] or ["signal: none (schema file only)"]
    lines += [f"note: {n}" for n in schema.notes]
    lines.append("source:")
    lines += schema.head
    if schema.more_lines:
        lines.append(f"[... {schema.more_lines} more lines]")
    return trim_snippet(lines)


def detect(
    repo: Path | str,
    repo_name: str | None = None,
    commit: str | None = None,
) -> list[Candidate]:
    """Run the rule over a checkout and return validated file-unit candidates.

    `repo_name` defaults to the checkout's folder name. scripts/clone_targets.py clones
    each target into targets/<name>, so that folder name is the target's `name` in
    targets.yaml (e.g. `spring-petclinic-microservices`). Pass it explicitly otherwise.
    `commit` defaults to the checkout's HEAD.
    """
    repo = Path(repo).resolve()
    repo_name = repo_name or repo.name
    commit = commit or head_commit(repo)
    services = find_services(repo)
    roots = [s.root for s in services]
    found: list[tuple[Service, SchemaFile]] = []
    protos: list[tuple[Service, Proto]] = []
    hits: list[RegistryHit] = []
    for service in services:
        for path in service_files(service, roots, ".avsc"):
            schema = avro_schema(path, service.root)
            if schema:
                found.append((service, schema))
        protos += [
            (service, _parse_proto(p, service.root, repo))
            for p in service_files(service, roots, ".proto")
        ]
        hits += registry_hits(service, roots)
    # Imports are matched across the whole repo: a shared proto module often holds them.
    all_protos = [p for _, p in protos]
    found += [(service, proto_schema(proto, all_protos)) for service, proto in protos]
    found.sort(key=lambda f: (f[0].root, f[1].rel))
    return [
        Candidate.create(
            repo=repo_name,
            commit=commit,
            service=service.name,
            file=schema.rel,
            line_start=None,
            line_end=None,
            unit=Unit.FILE,
            pattern=PATTERN,
            category=CATEGORY,
            rule_id=RULE_ID,
            snippet=_snippet(service.name, schema, registry_signal(service, hits)),
        )
        for service, schema in found
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tc_detector.rules.contracts.event_schema_versioning"
    )
    p.add_argument("repo_path", type=Path)
    p.add_argument("--repo-name", help="targets.yaml name; defaults to the folder name")
    p.add_argument("--commit", help="pinned SHA; defaults to the checkout's HEAD")
    args = p.parse_args(argv)
    for candidate in detect(args.repo_path, args.repo_name, args.commit):
        print(candidate.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
