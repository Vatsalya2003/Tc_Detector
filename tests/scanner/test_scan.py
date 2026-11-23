"""Tests for scan(): finding services, naming them, grouping files, and repo_files."""

import shutil
import subprocess

import pytest

from tc_detector.scanner import Inventory, scan
from tests.scanner.fake_repo import (
    COMMIT,
    JAVA_DIR,
    POM,
    app_yml,
    fingerprint,
    shop_repo,
    write,
)


def by_name(inv: Inventory) -> dict:
    return {s.name: s for s in inv.services}


# ------------------------------------------------------------------ services and names


def test_parent_pom_is_not_a_service_and_each_module_is(tmp_path):
    inv = scan(shop_repo(tmp_path), "shop", COMMIT)
    assert [(s.name, s.root) for s in inv.services] == [
        ("orders-service", "shop-orders"),
        ("payments", "shop-payments"),
    ]


def test_name_comes_from_config_else_from_folder_minus_shared_prefix(tmp_path):
    services = by_name(scan(shop_repo(tmp_path), "shop", COMMIT))
    assert services["orders-service"].name_source == "spring.application.name"
    assert services["payments"].name_source == "folder"


def test_placeholder_app_name_falls_back_to_the_folder_name(tmp_path):
    shop_repo(tmp_path)
    yml = "spring:\n  application:\n    name: ${APP_NAME:orders}\n"
    write(tmp_path, "shop-orders/src/main/resources/application.yml", yml)
    services = by_name(scan(tmp_path, "shop", COMMIT))
    assert services["orders"].root == "shop-orders"
    assert services["orders"].name_source == "folder"


def test_name_in_bootstrap_or_properties_is_found(tmp_path):
    write(tmp_path, "a-one/pom.xml", POM)
    write(tmp_path, "a-one/src/main/resources/bootstrap.yml", app_yml("first"))
    write(tmp_path, "a-two/pom.xml", POM)
    write(
        tmp_path,
        "a-two/src/main/resources/application.properties",
        "spring.application.name=second",
    )
    assert sorted(by_name(scan(tmp_path, "r", COMMIT))) == ["first", "second"]


def test_two_services_with_the_same_name_is_an_error(tmp_path):
    for folder in ("x-one", "x-two"):
        write(tmp_path, f"{folder}/pom.xml", POM)
        write(tmp_path, f"{folder}/src/main/resources/application.yml", app_yml("same"))
    with pytest.raises(ValueError, match="both named 'same'"):
        scan(tmp_path, "r", COMMIT)


def test_nested_service_keeps_its_own_files(tmp_path):
    write(tmp_path, "outer/pom.xml", POM)
    write(tmp_path, f"outer/{JAVA_DIR}/Outer.java")
    write(tmp_path, "outer/inner/pom.xml", POM)
    write(tmp_path, f"outer/inner/{JAVA_DIR}/Inner.java")
    services = by_name(scan(tmp_path, "r", COMMIT))
    assert services["outer"].files["java"] == [f"{JAVA_DIR}/Outer.java"]
    assert services["inner"].root == "outer/inner"
    assert services["inner"].files["java"] == [f"{JAVA_DIR}/Inner.java"]
    assert services["inner"].files["build"] == ["pom.xml"]


def test_gradle_multi_project_root_is_not_a_service(tmp_path):
    write(tmp_path, "settings.gradle", "rootProject.name = 'shop'\ninclude 'api', 'worker'\n")
    write(tmp_path, "build.gradle", "plugins { id 'java' }\n")
    write(tmp_path, "api/build.gradle", "")
    write(tmp_path, "worker/build.gradle.kts", "")
    inv = scan(tmp_path, "r", COMMIT)
    assert [s.root for s in inv.services] == ["api", "worker"]
    assert by_name(inv)["worker"].files["build"] == ["build.gradle.kts"]
    assert inv.repo_files == ["build.gradle", "settings.gradle"]


def test_single_service_repo_is_the_root_folder(tmp_path):
    repo = tmp_path / "solo-app"
    write(repo, "pom.xml", POM)
    write(repo, f"{JAVA_DIR}/App.java")
    inv = scan(repo, None, COMMIT)
    assert inv.repo == "solo-app"
    assert [(s.name, s.root) for s in inv.services] == [("solo-app", ".")]
    assert inv.services[0].files["java"] == [f"{JAVA_DIR}/App.java"]


def test_no_service_folders_makes_the_root_one_service_named_after_the_repo(tmp_path):
    write(tmp_path, "docker-compose.yml")
    write(tmp_path, f"{JAVA_DIR}/App.java")
    write(tmp_path, "src/main/resources/logback.xml")
    write(tmp_path, "src/test/java/AppTest.java")  # still skipped
    inv = scan(tmp_path, "my-repo", COMMIT)
    assert [(s.name, s.root, s.name_source) for s in inv.services] == [
        ("my-repo", ".", "root-fallback")
    ]
    files = inv.services[0].files
    assert files["java"] == [f"{JAVA_DIR}/App.java"]
    assert files["logging"] == ["src/main/resources/logback.xml"]
    assert inv.repo_files == []
    assert inv.service_for("docker-compose.yml").name == "my-repo"


def test_root_fallback_uses_the_app_name_when_set(tmp_path):
    write(tmp_path, "src/main/resources/application.yml", app_yml("lonely-service"))
    inv = scan(tmp_path, "my-repo", COMMIT)
    assert [(s.name, s.name_source) for s in inv.services] == [("lonely-service", "root-fallback")]
    assert inv.services[0].files["config"] == ["src/main/resources/application.yml"]


# ------------------------------------------------------------------ files


def test_files_are_grouped_relative_to_the_service_root(tmp_path):
    services = by_name(scan(shop_repo(tmp_path), "shop", COMMIT))
    assert services["orders-service"].files == {
        "build": ["pom.xml"],
        "config": ["src/main/resources/application.yml"],
        "logging": ["src/main/resources/logback-spring.xml"],
        "java": [f"{JAVA_DIR}/OrderController.java"],
        "specs": ["src/main/resources/openapi.yaml"],
        "schemas": ["src/main/proto/order.proto"],
    }
    assert services["payments"].files == {
        "build": ["pom.xml"],
        "config": ["src/main/resources/application.properties"],
        "logging": ["src/main/resources/log4j2.xml"],
        "java": [f"{JAVA_DIR}/PaymentClient.java"],
        "specs": [],
        "schemas": ["src/main/avro/payment.avsc", "src/main/resources/events.asyncapi.yaml"],
    }


def test_test_code_build_output_and_node_modules_are_skipped(tmp_path):
    inv = scan(shop_repo(tmp_path), "shop", COMMIT)
    listed = inv.to_json()
    for skipped in ("OrderTest.java", "Order.class", "junk.jar", "index.js"):
        assert skipped not in listed


def test_files_outside_every_service_go_to_repo_files(tmp_path):
    inv = scan(shop_repo(tmp_path), "shop", COMMIT)
    assert inv.repo_files == ["README.md", "docker-compose.yml", "pom.xml"]


def test_spec_is_found_by_its_top_level_key_not_only_its_name(tmp_path):
    write(tmp_path, "pom.xml", POM)
    write(tmp_path, "src/main/resources/api.yaml", "openapi: 3.1.0\ninfo: {}\n")
    write(tmp_path, "src/main/resources/api.json", '{\n  "swagger": "2.0"\n}')
    write(tmp_path, "src/main/resources/nested.yaml", "docs:\n  openapi: 3.0.0\n")  # nested key
    files = scan(tmp_path, "r", COMMIT).services[0].files
    assert files["specs"] == ["src/main/resources/api.json", "src/main/resources/api.yaml"]


def test_package_named_test_under_src_main_is_kept(tmp_path):
    write(tmp_path, "pom.xml", POM)
    write(tmp_path, "src/main/java/com/shop/test/Helper.java")
    assert scan(tmp_path, "r", COMMIT).services[0].files["java"] == [
        "src/main/java/com/shop/test/Helper.java"
    ]


# ------------------------------------------------------------------ targets and commits


def test_subfolder_target_uses_given_name_and_paths_from_the_subfolder(tmp_path):
    write(tmp_path, "week1-monolith/pom.xml", POM)  # another week: must not be scanned
    sub = shop_repo(tmp_path / "week6-events")
    inv = scan(sub, "cs6510-checkout", COMMIT)
    assert inv.repo == "cs6510-checkout"
    assert [s.root for s in inv.services] == ["shop-orders", "shop-payments"]
    assert "week1-monolith/pom.xml" not in inv.repo_files


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_commit_is_read_from_git_when_not_given_even_in_a_subfolder(tmp_path):
    shop_repo(tmp_path / "week6-events")
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    assert scan(tmp_path / "week6-events", "r").commit == head.strip()


def test_no_commit_and_no_git_is_an_error(tmp_path, monkeypatch):
    # GIT_CEILING_DIRECTORIES stops git looking above tmp_path for a parent checkout.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    with pytest.raises(ValueError, match="--commit"):
        scan(shop_repo(tmp_path), "shop")


def test_missing_folder_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="not a folder"):
        scan(tmp_path / "nope", "r", COMMIT)


def test_scan_never_writes_to_the_target(tmp_path):
    repo = shop_repo(tmp_path / "repo")
    before = fingerprint(repo)
    scan(repo, "shop", COMMIT)
    assert fingerprint(repo) == before
