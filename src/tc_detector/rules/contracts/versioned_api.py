"""versioned-api detection. Owner: Abhi (B).

Pattern `versioned-api`, category `api-stability`, matching unit `file`. One candidate per
API spec file that carries a version, with `line_start`/`line_end` None. See
ground_truth/GUIDELINES.md, `versioned-api`.

Spec files looked at (never test code or build output; see common.py):
  OpenAPI/Swagger  a .yaml, .yml or .json file whose top level has an `openapi` or `swagger`
                   key, or whose name contains "openapi" or "swagger" (openapi.yaml,
                   swagger.json, orders-openapi.yml)
  Protobuf         a .proto file

Counts (any one version signal):
  info.version        OpenAPI/Swagger `info.version` is set
  versioned paths     a key under `paths` has a /v1-style segment (/v1/owners, /api/v2/pets)
  versioned base      Swagger 2 `basePath` or an OpenAPI 3 `servers[].url` has one (/api/v1)
  versioned package   the proto `package` has a version part (petclinic.v1, shop.v1beta1)

Doesn't count:
  - the Maven <version> in pom.xml (build version, not API version): build files are never
    read;
  - other YAML/JSON, e.g. an application.yml with an actuator `info.version`: not a spec;
  - a spec with no version and no versioned paths (GUIDELINES: is_tc false);
  - a controller with @RequestMapping("/owners") and no spec file: Java is never read;
  - a .proto whose package has no version part (a version only in its folder is not enough);
  - a spec that is not valid YAML/JSON (the tools that read specs can't read it either).

Left to Claude, noted in the snippet:
  - proto for events or for an API? A .proto for events belongs to event-schema-versioning.
    The snippet says whether the file declares a `service` with rpcs, or is imported by a
    proto that does. If neither, it notes that the file may be an event schema.
  - an info.version filled at build time (`${...}`, `@...@`) may be the build version.

Run by hand (prints one candidate JSON per line):
    uv run python -m tc_detector.rules.contracts.versioned_api \\
        targets/spring-petclinic-microservices
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from tc_detector.contracts.candidate import Candidate, Category, Unit
from tc_detector.rules.contracts.common import (
    Service,
    find_services,
    head_commit,
    service_files,
    trim_snippet,
)

PATTERN = "versioned-api"
CATEGORY = Category.API_STABILITY
RULE_ID = "api-stability-versioned-api-01"

SPEC_SUFFIXES = (".yaml", ".yml", ".json")
SPEC_NAME_WORDS = ("openapi", "swagger")
SOURCE_LINES = 30  # head of the file shown in the snippet
SOURCE_LINE_CHARS = 200  # a minified JSON spec is one huge line
SHOWN = 3  # list items shown before "+N more"

# Cheap first check before parsing a file: an `openapi:`/`swagger:` key anywhere.
# The parsed top level decides; this only skips files that can't be specs.
_SPEC_KEY = re.compile(r"(?:^|[{,])\s*[\"']?(?:openapi|swagger)[\"']?\s*:", re.MULTILINE)
_VERSION_SEGMENT = re.compile(r"/v\d+(?:\.\d+)*(?=/|$)", re.IGNORECASE)
_VERSION_PART = re.compile(r"v\d+(?:[a-z]+\d*)*")  # one package part: v1, v1beta1, v1p1beta1
_BUILD_PLACEHOLDER = re.compile(r"\$\{[^}]*\}|@[\w.-]+@")
_PROTO_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)
_PROTO_SYNTAX = re.compile(r"^\s*syntax\s*=\s*[\"'](\w+)[\"']\s*;", re.MULTILINE)
_PROTO_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
_PROTO_SERVICE = re.compile(r"\bservice\s+(\w+)\s*\{")
_PROTO_RPC = re.compile(r"\brpc\s+\w+\s*\(")
_PROTO_IMPORT = re.compile(
    r"^\s*import\s+(?:public\s+|weak\s+)?[\"']([^\"']+)[\"']\s*;", re.MULTILINE
)


@dataclass(frozen=True)
class SpecFile:
    """One spec file with at least one version signal, and what to tell Claude about it."""

    rel: str  # path relative to the service root, with "/"
    kind: str  # "OpenAPI 3.0.3", "Swagger 2.0", "protobuf (proto3)"
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


# ------------------------------------------------------------------- helpers


def _shown(items: list[str]) -> str:
    more = len(items) - SHOWN
    return ", ".join(items[:SHOWN]) + (f" +{more} more" if more > 0 else "")


def _scalar(value: object) -> str | None:
    """A YAML/JSON scalar as text; None for missing, empty, true/false or nested values."""
    if value is None or isinstance(value, bool | dict | list):
        return None
    return str(value).strip() or None


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


# ------------------------------------------------------------ OpenAPI/Swagger


def _load(path: Path, text: str) -> dict | None:
    """The file's top-level mapping, or None if it isn't valid JSON/YAML or isn't a mapping."""
    try:
        doc = json.loads(text) if path.suffix == ".json" else next(yaml.safe_load_all(text), None)
    except (ValueError, yaml.YAMLError):
        return None
    return doc if isinstance(doc, dict) else None


def openapi_signals(doc: dict) -> tuple[list[str], list[str]]:
    """Version signals and notes of one OpenAPI/Swagger document."""
    signals, notes = [], []
    info = doc.get("info")
    version = _scalar(info.get("version")) if isinstance(info, dict) else None
    if version:
        signals.append(f"info.version {version}")
        if _BUILD_PLACEHOLDER.search(version):
            notes.append(
                "info.version is filled at build time, so it may be the build version, "
                "not an API version"
            )
    raw_paths = doc.get("paths")
    paths = [p for p in raw_paths if isinstance(p, str)] if isinstance(raw_paths, dict) else []
    versioned = [p for p in paths if _VERSION_SEGMENT.search(p)]
    if versioned:
        signals.append(f"versioned paths ({len(versioned)} of {len(paths)}): {_shown(versioned)}")
    servers = doc.get("servers") if isinstance(doc.get("servers"), list) else []
    bases = [_scalar(doc.get("basePath"))]
    bases += [_scalar(s.get("url")) for s in servers if isinstance(s, dict)]
    versioned_bases = [b for b in bases if b and _VERSION_SEGMENT.search(b)]
    if versioned_bases:
        signals.append(f"versioned base path: {_shown(versioned_bases)}")
    return signals, notes


def openapi_spec(path: Path, service_root: Path) -> SpecFile | None:
    """The spec file at `path` if it is an OpenAPI/Swagger spec with a version signal."""
    text = _read(path)
    named = any(word in path.stem.lower() for word in SPEC_NAME_WORDS)
    if not named and not _SPEC_KEY.search(text):
        return None
    doc = _load(path, text)
    if doc is None:
        return None
    openapi, swagger = _scalar(doc.get("openapi")), _scalar(doc.get("swagger"))
    if not (named or openapi or swagger):
        return None  # an `openapi:` key, but nested or not a version: not a spec
    signals, notes = openapi_signals(doc)
    if not signals:
        return None
    if openapi:
        kind = f"OpenAPI {openapi}"
    elif swagger:
        kind = f"Swagger {swagger}"
    else:
        kind = "OpenAPI/Swagger by file name (no openapi/swagger key)"
    head, more = _head(text)
    rel = path.relative_to(service_root).as_posix()
    return SpecFile(rel, kind, signals, notes, head, more)


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
    )


def _imports(importer: Proto, proto: Proto) -> bool:
    """Does `importer` import `proto`? Import paths are relative to a proto source root."""
    return any(proto.repo_rel == i or proto.repo_rel.endswith("/" + i) for i in importer.imports)


def proto_spec(proto: Proto, all_protos: list[Proto]) -> SpecFile | None:
    """The .proto as a spec file if its package has a version part."""
    if not proto.package or not any(
        _VERSION_PART.fullmatch(part) for part in proto.package.split(".")
    ):
        return None
    if proto.services:
        notes = [f"declares service {', '.join(proto.services)} with {proto.rpcs} rpc(s)"]
    else:
        importers = [p.repo_rel for p in all_protos if p.services and _imports(p, proto)]
        if importers:
            notes = [f"no service of its own; imported by service proto {_shown(importers)}"]
        else:
            notes = [
                "no service or rpc, and no proto with a service imports it: if it defines "
                "events, it belongs to event-schema-versioning, not versioned-api"
            ]
    kind = f"protobuf ({proto.syntax})" if proto.syntax else "protobuf"
    head, more = _head(_read(proto.path))
    return SpecFile(proto.rel, kind, [f"versioned package {proto.package}"], notes, head, more)


# --------------------------------------------------------------------- output


def _snippet(service: str, spec: SpecFile) -> str:
    lines = [f"{PATTERN} candidate: service {service}, file {spec.rel}", f"spec: {spec.kind}"]
    lines += [f"signal: {s}" for s in spec.signals]
    lines += [f"note: {n}" for n in spec.notes]
    lines.append("source:")
    lines += spec.head
    if spec.more_lines:
        lines.append(f"[... {spec.more_lines} more lines]")
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
    found: list[tuple[Service, SpecFile]] = []
    protos: list[tuple[Service, Proto]] = []
    for service in services:
        for suffix in SPEC_SUFFIXES:
            for path in service_files(service, roots, suffix):
                spec = openapi_spec(path, service.root)
                if spec:
                    found.append((service, spec))
        protos += [
            (service, _parse_proto(p, service.root, repo))
            for p in service_files(service, roots, ".proto")
        ]
    # Imports are matched across the whole repo: a shared proto module often holds them.
    all_protos = [p for _, p in protos]
    for service, proto in protos:
        spec = proto_spec(proto, all_protos)
        if spec:
            found.append((service, spec))
    found.sort(key=lambda f: (f[0].root, f[1].rel))
    return [
        Candidate.create(
            repo=repo_name,
            commit=commit,
            service=service.name,
            file=spec.rel,
            line_start=None,
            line_end=None,
            unit=Unit.FILE,
            pattern=PATTERN,
            category=CATEGORY,
            rule_id=RULE_ID,
            snippet=_snippet(service.name, spec),
        )
        for service, spec in found
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tc_detector.rules.contracts.versioned_api")
    p.add_argument("repo_path", type=Path)
    p.add_argument("--repo-name", help="targets.yaml name; defaults to the folder name")
    p.add_argument("--commit", help="pinned SHA; defaults to the checkout's HEAD")
    args = p.parse_args(argv)
    for candidate in detect(args.repo_path, args.repo_name, args.commit):
        print(candidate.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
