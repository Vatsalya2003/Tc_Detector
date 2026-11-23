"""Step 2 of a scan: give each service folder its name.

The name is `spring.application.name` from the service's config, or else the folder
name minus the prefix all service folders share (`spring-petclinic-config-server`
becomes `config-server`). This is the same method as the stand-ins in
rules/contracts/common.py and rules/abstraction/gateway.py, so the scanner names
services the way the labels in ground_truth/ already do.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

# Where the name is looked for: application*/bootstrap* files in src/main/resources.
CONFIG_PREFIXES = ("application", "bootstrap")
CONFIG_SUFFIXES = (".yml", ".yaml", ".properties")
# The values of a service's name_source.
FROM_CONFIG = "spring.application.name"
FROM_FOLDER = "folder"
FROM_ROOT = "root-fallback"  # no service folders, so the scanned root is the one service

_PROP_APP_NAME = re.compile(r"^\s*spring\.application\.name\s*[=:]\s*(\S+)")


def _config_files(service_dir: Path) -> list[Path]:
    """application*/bootstrap* config of one service, application.* first, then by name."""
    resources = service_dir / "src" / "main" / "resources"
    if not resources.is_dir():
        return []
    files = [
        p
        for p in resources.iterdir()
        if p.is_file() and p.suffix in CONFIG_SUFFIXES and p.name.startswith(CONFIG_PREFIXES)
    ]
    return sorted(files, key=lambda p: (p.stem != "application", p.name))


def _usable(value: object) -> str | None:
    """The name, or None if it is empty or a `${...}` placeholder filled in at runtime."""
    if isinstance(value, str) and value.strip() and "${" not in value:
        return value.strip()
    return None


def _yaml_app_name(text: str) -> str | None:
    """Both spellings: nested `spring: application: name:` and the flat dotted key."""
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return None
    for doc in docs:  # a YAML file can hold several documents separated by ---
        if not isinstance(doc, dict):
            continue
        value = doc.get("spring.application.name")
        spring = doc.get("spring")
        if value is None and isinstance(spring, dict):
            app = spring.get("application")
            value = app.get("name") if isinstance(app, dict) else spring.get("application.name")
        if name := _usable(value):
            return name
    return None


def app_name(service_dir: Path) -> str | None:
    """`spring.application.name` of one service, or None if it isn't set."""
    for path in _config_files(service_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".properties":
            for line in text.splitlines():
                m = _PROP_APP_NAME.match(line)
                if m and (name := _usable(m.group(1))):
                    return name
        elif name := _yaml_app_name(text):
            return name
    return None


def common_dash_prefix(names: list[str]) -> str:
    """`spring-petclinic-` for ["spring-petclinic-a", "spring-petclinic-b"]; never a whole name."""
    if len(names) < 2:
        return ""
    split = [n.split("-") for n in names]
    prefix: list[str] = []
    for tokens in zip(*split, strict=False):
        if len(set(tokens)) != 1:
            break
        prefix.append(tokens[0])
    if any(len(s) <= len(prefix) for s in split):  # keep at least one word of every name
        prefix = prefix[:-1]
    return "-".join(prefix) + "-" if prefix else ""


def name_services(root: Path, roots: list[str]) -> list[tuple[str, str, str]]:
    """(root, name, name_source) for every service folder.

    Raises ValueError if two services get the same name: their candidate ids would clash.
    """
    folders = [(root / r).resolve().name for r in roots]  # "." is named after the root itself
    prefix = common_dash_prefix(folders)
    named = []
    for rel, folder in zip(roots, folders, strict=True):
        if name := app_name(root / rel):
            named.append((rel, name, FROM_CONFIG))
        else:
            named.append((rel, folder.removeprefix(prefix), FROM_FOLDER))
    seen: dict[str, str] = {}
    for rel, name, _ in named:
        if name in seen:
            raise ValueError(f"two services are both named {name!r}: {seen[name]} and {rel}")
        seen[name] = rel
    return named
