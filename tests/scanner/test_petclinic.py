"""The scanner on the real PetClinic checkout (skipped only if it isn't cloned anywhere).

Never point these tests at the held-out repo: it is scored once, after Dec 1.
"""

from pathlib import Path

import pytest

from tc_detector.contracts.label import load_labels
from tc_detector.rules.contracts.common import find_services
from tc_detector.scanner import scan

REPO_ROOT = Path(__file__).parents[2]
# Where scripts/clone_targets.py puts it first, then a checkout next to this repo.
PLACES = [
    REPO_ROOT / "targets" / "spring-petclinic-microservices",
    REPO_ROOT.parent / "spring-petclinic-microservices",
]
PETCLINIC = next((p for p in PLACES if p.is_dir()), None)
LABELS = REPO_ROOT / "ground_truth" / "petclinic.json"
NAMES = [
    "admin-server",
    "api-gateway",
    "config-server",
    "customers-service",
    "discovery-server",
    "genai-service",
    "vets-service",
    "visits-service",
]

pytestmark = pytest.mark.skipif(
    PETCLINIC is None, reason="PetClinic not cloned (run scripts/clone_targets.py)"
)


@pytest.fixture(scope="module")
def inv():
    return scan(PETCLINIC, "spring-petclinic-microservices")


def test_exactly_eight_services_with_the_agreed_names(inv):
    assert sorted(s.name for s in inv.services) == NAMES
    for s in inv.services:
        assert s.root == f"spring-petclinic-{s.name}"


def test_config_server_is_the_one_named_after_its_folder(inv):
    assert [s.name for s in inv.services if s.name_source == "folder"] == ["config-server"]


def test_names_match_the_contracts_stand_in(inv):
    stand_in = {s.root.name: s.name for s in find_services(PETCLINIC)}
    assert {s.root: s.name for s in inv.services} == stand_in


def test_every_labelled_file_is_in_the_inventory(inv):
    for label in load_labels(LABELS):
        service = next(s for s in inv.services if s.name == label.service)
        assert label.file in service.files["java"], label.file


def test_root_pom_and_docker_compose_are_repo_files(inv):
    assert {"pom.xml", "docker-compose.yml"} <= set(inv.repo_files)
    assert not any("/src/test/" in f for s in inv.services for f in s.files["java"])
