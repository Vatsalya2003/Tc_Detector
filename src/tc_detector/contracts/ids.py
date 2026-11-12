"""How a candidate is named: its id, the naming patterns, and the snippet size limit.

These are kept apart from the checks so other code (e.g. evaluation) can build ids too.
Read this file to learn the id format and naming rules. Read checks.py next.
"""

import re

from tc_detector.contracts.enums import Unit

# The snippet is sent to Claude, and we pay per character, so we cap its size.
SNIPPET_MAX_CHARS = 2000

# "Kebab-case" means lowercase letters/digits, with words joined by single dashes.
#   passes: "tracing-span", "gateway", "api-v2"
#   fails:  "TracingSpan", "tracing_span", "-tracing", "tracing--span", "tracing-span\n"
KEBAB_CASE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

# A rule id: kebab-case words, then a dash and exactly two digits.
#   passes: "observability-tracing-01", "api-stability-versioning-12"
#   fails:  "OBS-01", "observability-tracing-1", "observability-tracing-01\n"
RULE_ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*-[0-9]{2}")

# Both patterns must be used with fullmatch() ("the WHOLE string must match").
# Plain match() with "$" would wrongly accept a trailing newline.


def build_id(
    repo: str,
    service: str,
    file: str | None,
    line_start: int | None,
    line_end: int | None,
    unit: Unit | str,
    pattern: str,
) -> str:
    """Make a candidate's id from its fields, so the same finding always gets the same id.

    Format is repo:service:file:location:pattern, for example
        petclinic:api-gateway:src/GatewayConfig.java:12-40:gateway       (line_range)
        petclinic:api-gateway:src/main/resources/logback.xml:file:corr   (file)
        petclinic:api-gateway:-:service:gateway                          (service, no file)
    """
    unit = Unit(unit)
    # Line ranges put their numbers here ("12-40"); file and service units have no
    # line numbers, so they put the unit's name here instead ("file" / "service").
    location = f"{line_start}-{line_end}" if unit == Unit.LINE_RANGE else unit.value
    file_part = file if file else "-"  # "-" means "no file"
    return f"{repo}:{service}:{file_part}:{location}:{pattern}"
