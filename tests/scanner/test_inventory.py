"""Tests for Inventory: finding a file's service, a service's folder, and JSON round trips."""

import json

import pytest

from tc_detector.scanner import Inventory, Service, scan
from tests.scanner.fake_repo import COMMIT, POM, shop_repo, write


def test_service_for_finds_the_service_holding_a_path(tmp_path):
    inv = scan(shop_repo(tmp_path), "shop", COMMIT)
    assert inv.service_for("shop-orders/src/main/resources/application.yml").name == (
        "orders-service"
    )
    assert inv.service_for("shop-orders").name == "orders-service"
    assert inv.service_for("docker-compose.yml") is None
    # A folder that only starts with the same letters is not inside the service.
    assert inv.service_for("shop-orders-old/pom.xml") is None


def test_service_for_picks_the_deepest_service(tmp_path):
    write(tmp_path, "outer/pom.xml", POM)
    write(tmp_path, "outer/inner/pom.xml", POM)
    inv = scan(tmp_path, "r", COMMIT)
    assert inv.service_for("outer/inner/src/A.java").name == "inner"
    assert inv.service_for("outer/src/B.java").name == "outer"


def test_service_root_gives_the_folder_and_rejects_unknown_names(tmp_path):
    inv = scan(shop_repo(tmp_path), "shop", COMMIT)
    assert inv.service_root("payments") == "shop-payments"
    with pytest.raises(KeyError):
        inv.service_root("nope")


def test_json_round_trip_keeps_everything(tmp_path):
    inv = scan(shop_repo(tmp_path), "shop", COMMIT)
    assert Inventory.from_json(inv.to_json()) == inv
    path = tmp_path / "inventory.json"
    inv.save(path)
    assert Inventory.load(path) == inv


def test_json_has_the_agreed_shape(tmp_path):
    data = json.loads(scan(shop_repo(tmp_path), "shop", COMMIT).to_json())
    assert list(data) == ["repo", "commit", "services", "repo_files"]
    assert list(data["services"][0]) == ["name", "root", "name_source", "files"]
    assert list(data["services"][0]["files"]) == [
        "build",
        "config",
        "logging",
        "java",
        "specs",
        "schemas",
    ]


def test_from_json_rejects_a_missing_group():
    service = Service("a", "a", "folder")
    data = json.loads(Inventory("r", COMMIT, [service]).to_json())
    del data["services"][0]["files"]["specs"]
    with pytest.raises(ValueError, match="specs"):
        Inventory.from_json(json.dumps(data))
