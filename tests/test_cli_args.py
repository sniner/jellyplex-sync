"""Argument-parser contract of the `jellyplex` CLI.

Pins that `--json` exists exactly where a JSON document is actually
produced: `import` has no JSON output yet, so the flag must be rejected
there instead of silently swallowing the run's output.
"""

from __future__ import annotations

import pytest

from jellyplex_sync.cli.main import _build_parser


def test_import_rejects_json() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["import", "--json", "src", "dst"])
    assert exc_info.value.code == 2


def test_import_defaults_json_false() -> None:
    args = _build_parser().parse_args(["import", "src", "dst"])
    assert args.json is False


@pytest.mark.parametrize("command", ["sync", "diff", "plan"])
def test_json_accepted_where_supported(command: str) -> None:
    args = _build_parser().parse_args([command, "--json", "src", "dst"])
    assert args.json is True
