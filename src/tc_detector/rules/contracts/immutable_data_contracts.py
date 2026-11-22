"""immutable-data-contracts detection. Owner: Abhi (B).

Pattern `immutable-data-contracts`, category `api-stability`, matching unit `file`
(confirmed by owner). One candidate per Java file holding at least one wire DTO, with
`line_start`/`line_end` None. See ground_truth/GUIDELINES.md, `immutable-data-contracts`.

A class or record (nested ones too, local ones in method bodies not) counts when it has
a contract signal AND a wire sign, and is not excluded.

Contract signals (any one):
  record          a Java `record`
  lombok @Value   Lombok `@Value` on a class: written `@lombok.Value`, or `@Value` with
                  `import lombok.Value` / `import lombok.*`. Spring's `@Value("${...}")`
                  sits on fields, not classes, so it never matches.
  ignoreUnknown   `@JsonIgnoreProperties(ignoreUnknown = true)` on the type

Wire signs (any one; GUIDELINES: records used only inside one service are not contracts):
  Jackson         a Jackson `@Json...` annotation on the type, its fields or components
  folder          a folder on its path is dto, api, web, rest, client, contract, event,
                  message or payload (or the plural; also `messaging`)
  name            its name ends in Dto, DTO, Request, Response, Details, Event, Message
                  or Payload
  used            a file of the same service that does HTTP or messaging names the type:
                  it has @RestController, @Controller, @FeignClient, @HttpExchange (or
                  @GetExchange...), a Kafka/Rabbit/JMS listener, or uses WebClient,
                  RestTemplate, RestClient, KafkaTemplate, RabbitTemplate, JmsTemplate or
                  StreamBridge. A DTO declared inside such a file counts too.

Excluded, with every type nested inside them:
  - persistence models: @Entity, @Embeddable, @MappedSuperclass, @Table, @Document
    (GUIDELINES negative: customers-service Owner.java, an @Entity with setters);
  - configuration: @ConfigurationProperties (a config record is read from properties,
    never sent over the wire).

Left to Claude and the labeller, not judged here: deep immutability. A record with a List
component is only shallowly immutable, and an ignoreUnknown class may have setters. Both
still count by the signals above; the snippet notes them.

Run by hand (prints one candidate JSON per line):
    uv run python -m tc_detector.rules.contracts.immutable_data_contracts \\
        targets/spring-petclinic-microservices
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Parser

from tc_detector.contracts.candidate import Candidate, Category, Unit
from tc_detector.rules.contracts.common import (
    Service,
    find_services,
    head_commit,
    service_files,
    trim_snippet,
)

PATTERN = "immutable-data-contracts"
CATEGORY = Category.API_STABILITY
RULE_ID = "api-stability-immutable-data-contracts-01"

EXCLUDING_ANNOTATIONS = {
    "Entity",
    "Embeddable",
    "MappedSuperclass",
    "Table",
    "Document",
    "ConfigurationProperties",
}
WIRE_FOLDERS = {
    "dto",
    "dtos",
    "api",
    "web",
    "rest",
    "client",
    "clients",
    "contract",
    "contracts",
    "event",
    "events",
    "message",
    "messages",
    "messaging",
    "payload",
    "payloads",
}
WIRE_SUFFIXES = ("Dto", "DTO", "Request", "Response", "Details", "Event", "Message", "Payload")
BOUNDARY_ANNOTATIONS = {
    "RestController",
    "Controller",
    "FeignClient",
    "HttpExchange",
    "GetExchange",
    "PostExchange",
    "PutExchange",
    "PatchExchange",
    "DeleteExchange",
    "KafkaListener",
    "RabbitListener",
    "JmsListener",
}
BOUNDARY_TYPES = {
    "WebClient",
    "RestTemplate",
    "RestClient",
    "KafkaTemplate",
    "RabbitTemplate",
    "JmsTemplate",
    "StreamBridge",
}
COLLECTION_TYPES = {"List", "Set", "Map", "Collection", "Iterable", "Queue", "Deque"}

_CANDIDATE_DECLS = {"class_declaration", "record_declaration"}
_ALL_TYPE_DECLS = _CANDIDATE_DECLS | {
    "interface_declaration",
    "enum_declaration",
    "annotation_type_declaration",
}
# Where member types live. Method bodies are not here, so local records are never walked.
_BODIES = {
    "class_body",
    "interface_body",
    "enum_body",
    "enum_body_declarations",
    "annotation_type_body",
}
_ANNOTATIONS = {"annotation", "marker_annotation"}
_LOMBOK_VALUE_IMPORT = re.compile(r"^import\s+lombok\s*\.\s*(Value|\*)\s*;")
_SETTER = re.compile(r"set[A-Z]\w*")

_parser = Parser(Language(tsjava.language()))


@dataclass(frozen=True)
class DtoType:
    """One class or record that passed the rule, with the evidence for it."""

    name: str
    start: int  # 1-indexed first line, annotations included
    end: int  # 1-indexed last line
    signals: list[str]
    wire: list[str]
    notes: list[str]


@dataclass
class JavaFile:
    """One parsed Java file of a service."""

    path: Path
    rel: str  # path relative to the service root, with "/"
    root: Node
    names: set[str]  # identifiers and type names in the code (never comments or strings)
    boundary: bool  # does this file do HTTP or messaging?


# ------------------------------------------------------------------ tree helpers


def _text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def _annotations(decl: Node) -> list[Node]:
    """The annotations written on a declaration (not on its members)."""
    for child in decl.children:
        if child.type == "modifiers":
            return [a for a in child.children if a.type in _ANNOTATIONS]
    return []


def _annotation_name(annotation: Node) -> str:
    """`Value` for both `@Value` and `@lombok.Value`."""
    return _text(annotation.child_by_field_name("name")).rsplit(".", 1)[-1]


def _is_ignore_unknown(annotation: Node) -> bool:
    """True for `@JsonIgnoreProperties(ignoreUnknown = true)`, in any argument order."""
    if _annotation_name(annotation) != "JsonIgnoreProperties":
        return False
    args = annotation.child_by_field_name("arguments")
    if args is None:
        return False
    return any(
        pair.type == "element_value_pair"
        and _text(pair.child_by_field_name("key")) == "ignoreUnknown"
        and _text(pair.child_by_field_name("value")) == "true"
        for pair in args.children
    )


def _imports_lombok_value(root: Node) -> bool:
    return any(
        child.type == "import_declaration" and _LOMBOK_VALUE_IMPORT.match(_text(child))
        for child in root.children
    )


def _walk(node: Node) -> Iterator[Node]:
    """Every node below `node`, in source order."""
    stack = list(reversed(node.children))
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _own_nodes(decl: Node) -> Iterator[Node]:
    """Nodes of a declaration, skipping the types nested inside it (those are judged alone)."""
    stack = list(reversed(decl.children))
    while stack:
        n = stack.pop()
        if n.type in _ALL_TYPE_DECLS:
            continue
        yield n
        stack.extend(reversed(n.children))


def _declared_types(root: Node) -> Iterator[Node]:
    """Top-level and member classes/records, skipping excluded ones and all they contain."""
    stack = list(reversed(root.children))
    while stack:
        n = stack.pop()
        if n.type in _ALL_TYPE_DECLS:
            if any(_annotation_name(a) in EXCLUDING_ANNOTATIONS for a in _annotations(n)):
                continue
            if n.type in _CANDIDATE_DECLS:
                yield n
        if n.type in _ALL_TYPE_DECLS | _BODIES:
            stack.extend(reversed(n.children))


# --------------------------------------------------------------------- signals


def contract_signals(decl: Node, lombok_imported: bool) -> list[str]:
    """Which contract signals one class or record has (empty list: none)."""
    found = []
    if decl.type == "record_declaration":
        found.append("record")
    for a in _annotations(decl):
        full = _text(a.child_by_field_name("name"))
        is_lombok = full == "lombok.Value" or (full == "Value" and lombok_imported)
        if decl.type == "class_declaration" and is_lombok:
            found.append("Lombok @Value")
        if _is_ignore_unknown(a):
            found.append("@JsonIgnoreProperties(ignoreUnknown = true)")
    return found


def _has_jackson(decl: Node) -> bool:
    return any(
        n.type in _ANNOTATIONS and _annotation_name(n).startswith("Json") for n in _own_nodes(decl)
    )


def wire_signs(name: str, rel: str, has_jackson: bool, used_by: list[str]) -> list[str]:
    """Why a type looks like it is sent over the wire (empty list: no reason)."""
    found = []
    if has_jackson:
        found.append("Jackson annotation")
    folders = [p for p in Path(rel).parent.parts if p.lower() in WIRE_FOLDERS]
    if folders:
        found.append(f"folder '{folders[-1]}'")
    suffix = next((s for s in WIRE_SUFFIXES if name.endswith(s) and name != s), None)
    if suffix:
        found.append(f"name ends in '{suffix}'")
    if used_by:
        shown = ", ".join(used_by[:3]) + (f" +{len(used_by) - 3} more" if len(used_by) > 3 else "")
        found.append(f"used by {shown}")
    return found


def _notes(decl: Node) -> list[str]:
    """Things Claude should know that don't change the verdict."""
    notes = []
    if decl.type == "record_declaration":
        params = decl.child_by_field_name("parameters")
        for p in params.children if params is not None else []:
            if p.type != "formal_parameter":
                continue
            ptype = p.child_by_field_name("type")
            outer = _text(ptype).split("<", 1)[0].strip()
            if ptype is not None and (ptype.type == "array_type" or outer in COLLECTION_TYPES):
                field = _text(p.child_by_field_name("name"))
                notes.append(f"only shallowly immutable: {field} is a {outer or _text(ptype)}")
    setters = sorted(
        {
            _text(n.child_by_field_name("name"))
            for n in _own_nodes(decl)
            if n.type == "method_declaration"
            and _SETTER.fullmatch(_text(n.child_by_field_name("name")))
        }
    )
    if setters:
        notes.append(f"mutable: has setter(s) {', '.join(setters)}")
    return notes


# -------------------------------------------------------------------- per file


def _parse(path: Path, service_root: Path) -> JavaFile:
    root = _parser.parse(path.read_bytes()).root_node
    names: set[str] = set()
    boundary = False
    for n in _walk(root):
        if n.type in ("identifier", "type_identifier"):
            names.add(_text(n))
        elif n.type in _ANNOTATIONS and _annotation_name(n) in BOUNDARY_ANNOTATIONS:
            boundary = True
    boundary = boundary or bool(names & BOUNDARY_TYPES)
    return JavaFile(path, path.relative_to(service_root).as_posix(), root, names, boundary)


def dto_types(java: JavaFile, boundary_files: list[JavaFile]) -> list[DtoType]:
    """The classes/records in one file that have a contract signal and a wire sign."""
    lombok = _imports_lombok_value(java.root)
    found = []
    for decl in _declared_types(java.root):
        signals = contract_signals(decl, lombok)
        if not signals:
            continue
        name = _text(decl.child_by_field_name("name"))
        used_by = sorted(b.path.name for b in boundary_files if name in b.names)
        wire = wire_signs(name, java.rel, _has_jackson(decl), used_by)
        if not wire:
            continue
        start, end = decl.start_point.row + 1, decl.end_point.row + 1
        found.append(DtoType(name, start, end, signals, wire, _notes(decl)))
    return found


def _snippet(service: str, rel: str, types: list[DtoType], source: list[str]) -> str:
    lines = [f"{PATTERN} candidate: service {service}, file {rel}"]
    for t in types:
        lines.append(
            f"type {t.name} (line {t.start}): {', '.join(t.signals)}; wire: {', '.join(t.wire)}"
        )
        lines += [f"  note: {n}" for n in t.notes]
    lines.append("source:")
    # One block per outermost type: a nested DTO is already inside its parent's lines.
    last_end = 0
    for t in sorted(types, key=lambda t: t.start):
        if t.start <= last_end:
            continue
        if last_end:
            lines.append("...")
        lines += source[t.start - 1 : t.end]
        last_end = t.end
    return trim_snippet(lines)


# ---------------------------------------------------------------------- output


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
    candidates = []
    for service in services:
        candidates += _service_candidates(service, roots, repo_name, commit)
    return candidates


def _service_candidates(
    service: Service, roots: list[Path], repo_name: str, commit: str
) -> list[Candidate]:
    files = [_parse(p, service.root) for p in service_files(service, roots, ".java")]
    boundary_files = [f for f in files if f.boundary]
    candidates = []
    for java in files:
        types = dto_types(java, boundary_files)
        if not types:
            continue
        # Split on "\n" only, as tree-sitter counts lines; splitlines() would also break
        # on form feeds and Unicode separators and shift the line numbers.
        text = java.path.read_text(encoding="utf-8", errors="replace")
        source = [line.removesuffix("\r") for line in text.split("\n")]
        candidates.append(
            Candidate.create(
                repo=repo_name,
                commit=commit,
                service=service.name,
                file=java.rel,
                line_start=None,
                line_end=None,
                unit=Unit.FILE,
                pattern=PATTERN,
                category=CATEGORY,
                rule_id=RULE_ID,
                snippet=_snippet(service.name, java.rel, types, source),
            )
        )
    return candidates


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tc_detector.rules.contracts.immutable_data_contracts"
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
