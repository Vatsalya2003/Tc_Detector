"""Command-line entry point: `uv run tc-detect` runs main() below.

For now it only prints the version; scan/rules/report subcommands come later.
"""

from importlib.metadata import version


def main() -> None:
    """Print the tool's name and version."""
    # Read the version from the installed package, so pyproject.toml stays the
    # only place it is written and the two can never disagree.
    print(f"tc-detect {version('tc-detector')}")


# Lets you also run it as `python -m tc_detector.cli`.
if __name__ == "__main__":
    main()
