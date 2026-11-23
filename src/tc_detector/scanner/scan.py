"""Stage 1 of the pipeline: scan a target repo into an Inventory.

    from tc_detector.scanner import scan
    inv = scan("../spring-petclinic-microservices")
    inv.service_root("customers-service")   # "spring-petclinic-customers-service"

The scan only reads the target: it lists files, reads config/build files and asks git
for the commit. It never writes there.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tc_detector.scanner.groups import group_of
from tc_detector.scanner.inventory import Inventory, Service
from tc_detector.scanner.naming import FROM_ROOT, app_name, name_services
from tc_detector.scanner.walk import service_roots, walk_files


def head_commit(folder: Path) -> str | None:
    """The git HEAD SHA of the checkout `folder` is in (a subfolder works), else None."""
    try:
        out = subprocess.run(
            ["git", "-C", str(folder), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def scan(root: Path | str, repo_name: str | None = None, commit: str | None = None) -> Inventory:
    """Scan the folder `root` (a whole repo, or a subfolder of one).

    `repo_name` defaults to the folder's name; for a subfolder target (targets.yaml `path:`)
    pass the target's `name`. `commit` defaults to git's HEAD. Raises ValueError if the
    folder is missing, the commit can't be found, or two services share a name.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"not a folder: {root}")
    commit = commit or head_commit(root)
    if not commit:
        raise ValueError(f"{root} is not a git checkout; pass the commit with --commit")

    repo_name = repo_name or root.name
    files = walk_files(root)
    named = name_services(root, service_roots(root, files))
    if not named:
        # No build file anywhere: the whole scanned folder is one service, as the rules'
        # stand-ins do, so rules still look at its files instead of silently finding nothing.
        named = [(".", app_name(root) or repo_name, FROM_ROOT)]
    inv = Inventory(repo_name, commit, [Service(n, r, s) for r, n, s in named])

    # Each file goes to its deepest service (a nested service keeps its own files).
    for path in files:
        service = inv.service_for(path)
        if service is None:
            inv.repo_files.append(path)
            continue
        rel = path if service.root == "." else path.removeprefix(service.root + "/")
        group = group_of(rel, root / path)
        if group:
            service.files[group].append(rel)
    return inv
