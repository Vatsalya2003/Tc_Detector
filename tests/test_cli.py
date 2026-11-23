"""Tests for the command-line entry point (the `scan` command is tested in tests/scanner/)."""

from importlib.metadata import version

import pytest

from tc_detector.cli import main


def test_main_prints_the_version(capsys):
    """`tc-detect` prints its name and the version from pyproject.toml."""
    # capsys is a pytest helper that captures what main() prints.
    # main([]) is `tc-detect` with no arguments (main() alone would read pytest's own).
    assert main([]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == f"tc-detect {version('tc-detector')}"


def test_version_flag_prints_the_version(capsys):
    """`tc-detect --version` prints the same line and exits cleanly."""
    with pytest.raises(SystemExit) as stop:
        main(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.strip() == f"tc-detect {version('tc-detector')}"
