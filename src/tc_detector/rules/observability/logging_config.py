"""Log patterns with a trace/correlation ID, for the structured-logging rule. Owner: Vatsalya (A).

Two kinds of file set a log pattern:
  logging files  logback*.xml, log4j2* (the scanner's `logging` group): an ID inside a
                 <pattern>, a pattern="..." attribute, a <property name="...PATTERN..."
                 value="...">, or a `...pattern = ...` / `...pattern: ...` line;
  config files   application*/bootstrap* (the scanner's `config` group): an ID in a
                 logging.pattern.* value, flat (.properties) or nested (YAML).

Each function returns (line, what was found) pairs; structured_logging.py turns a file
with any pair into a candidate. Comments are blanked first, so they never count.
"""

from __future__ import annotations

import re

import yaml

from tc_detector.rules.observability.common import line_at, xml_code

# An ID: traceId or correlationId in any case, with or without - or _.
ID = re.compile(r"trace[-_]?id|correlation[-_]?id", re.IGNORECASE)

# Each pattern captures the pattern text (group "p"), searched for an ID afterwards.
_LOG_PATTERNS = [
    re.compile(r"<pattern>(?P<p>.*?)</pattern>", re.DOTALL | re.IGNORECASE),
    re.compile(r"\bpattern\s*=\s*\"(?P<p>[^\"]*)\"", re.IGNORECASE),
    re.compile(r"<property\s+name=\"[^\"]*pattern[^\"]*\"\s+value=\"(?P<p>[^\"]*)\"", re.I),
    re.compile(r"^[ \t]*\"?[\w.-]*pattern\"?[ \t]*[=:][ \t]*(?P<p>.+)$", re.I | re.MULTILINE),
]
_PROP_LOGGING_PATTERN = re.compile(
    r"^[ \t]*(logging\.pattern\.[\w.-]+)[ \t]*[=:](?P<p>.*)$", re.MULTILINE
)
_HASH_COMMENT = re.compile(r"^[ \t]*[#!].*$", re.MULTILINE)  # properties/YAML comment lines


def logging_file_signals(rel: str, text: str) -> list[tuple[int, str]]:
    # Comments are blanked line for line, so a commented-out pattern never counts.
    code = xml_code(text) if rel.endswith(".xml") else _HASH_COMMENT.sub("", text)
    found: dict[int, str] = {}  # one signal per line, even if two regexes match it
    for pattern in _LOG_PATTERNS:
        for m in pattern.finditer(code):
            if ident := ID.search(m.group("p")):
                found.setdefault(line_at(code, m.start("p")), f"log pattern with {ident.group()}")
    return sorted(found.items())


def _yaml_logging_patterns(node: object, path: tuple[str, ...]) -> list[tuple[int, str]]:
    """(line, key) of every string value under logging.pattern.* in a composed YAML node."""
    if isinstance(node, yaml.ScalarNode):
        is_pattern = path[:2] == ("logging", "pattern") and ID.search(str(node.value))
        return [(node.start_mark.line + 1, ".".join(path))] if is_pattern else []
    if isinstance(node, yaml.MappingNode):
        return [
            hit
            for k, v in node.value
            for hit in _yaml_logging_patterns(v, (*path, *str(k.value).split(".")))
        ]
    if isinstance(node, yaml.SequenceNode):
        return [hit for item in node.value for hit in _yaml_logging_patterns(item, path)]
    return []


def config_signals(rel: str, text: str) -> list[tuple[int, str]]:
    if rel.endswith(".properties"):
        code = _HASH_COMMENT.sub("", text)  # same lines as `text`, comments emptied
        hits = [
            (line_at(code, m.start()), m.group(1))
            for m in _PROP_LOGGING_PATTERN.finditer(code)
            if ID.search(m.group("p"))
        ]
    else:
        try:
            docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
        except yaml.YAMLError:
            return []
        hits = [hit for doc in docs for hit in _yaml_logging_patterns(doc, ())]
    return [(line, f"{key} with a trace/correlation ID") for line, key in hits]
