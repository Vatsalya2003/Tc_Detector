"""Tests for the command-line entry point."""

from importlib.metadata import version

from tc_detector.cli import main


def test_main_prints_the_version(capsys):
    """`tc-detect` prints its name and the version from pyproject.toml."""
    # capsys is a pytest helper that captures what main() prints.
    main()
    printed = capsys.readouterr().out.strip()
    assert printed == f"tc-detect {version('tc-detector')}"
