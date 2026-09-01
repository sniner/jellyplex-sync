"""Backward-compatible ``jellyplex-sync`` entry point.

A thin alias for ``jellyplex sync``: the ``sync`` subcommand is
inserted into the argument list and the main CLI takes over. Same
options, same behaviour, one parser to maintain instead of two
copies that would have to be kept in step by hand.
"""

from __future__ import annotations

import sys

from jellyplex_sync.cli import main as cli_main


def main() -> None:
    sys.argv = [sys.argv[0], "sync", *sys.argv[1:]]
    cli_main.main()


if __name__ == "__main__":
    main()
