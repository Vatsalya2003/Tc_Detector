"""Tests for `tc-detect scan`."""

import pytest

from tc_detector.cli import main
from tc_detector.scanner import Inventory
from tests.scanner.fake_repo import COMMIT, fingerprint, shop_repo


def test_scan_writes_inventory_json_and_prints_a_summary(tmp_path, capsys):
    repo = shop_repo(tmp_path / "repo")
    out = tmp_path / "results"
    code = main(
        ["scan", "--repo", str(repo), "--out", str(out), "--repo-name", "shop", "--commit", COMMIT]
    )
    assert code == 0
    inv = Inventory.load(out / "inventory.json")
    assert (inv.repo, inv.commit, len(inv.services)) == ("shop", COMMIT, 2)
    # 6 + 6 grouped service files, plus README.md, docker-compose.yml and the parent pom.
    assert capsys.readouterr().out.strip() == (f"2 services, 15 files -> {out / 'inventory.json'}")


def test_out_inside_the_scanned_repo_is_refused(tmp_path):
    repo = shop_repo(tmp_path / "repo")
    before = fingerprint(repo)
    with pytest.raises(SystemExit, match="inside the scanned repo"):
        main(["scan", "--repo", str(repo), "--out", str(repo / "results"), "--commit", COMMIT])
    assert fingerprint(repo) == before


def test_scan_error_is_a_clear_message(tmp_path):
    with pytest.raises(SystemExit, match="error: not a folder"):
        main(
            [
                "scan",
                "--repo",
                str(tmp_path / "nope"),
                "--out",
                str(tmp_path / "o"),
                "--commit",
                COMMIT,
            ]
        )
