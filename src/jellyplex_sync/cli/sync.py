#!/usr/bin/python3
from __future__ import annotations

import argparse
import logging
import sys

import jellyplex_sync as jp

_SUBCOMMANDS = {"sync", "diff", "plan"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jellyplex-sync",
        description="Convert a media library between Plex and Jellyfin layouts.",
    )

    # Flags shared by every subcommand. Use a parent parser so they can be
    # given either before or after the subcommand name.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show more information messages.",
    )
    common.add_argument(
        "--debug",
        action="store_true",
        help="Show debug messages.",
    )
    common.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON document on stdout. Logs continue to go to stderr.",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    sync_p = sub.add_parser(
        "sync",
        parents=[common],
        help="Mirror a source library into the target layout (default).",
    )
    _add_io_args(sync_p)
    mode = sync_p.add_mutually_exclusive_group()
    mode.add_argument(
        "--hardlink",
        dest="mode",
        action="store_const",
        const="hardlink",
        help="Use hardlinks (default; needs source and target on the same filesystem).",
    )
    mode.add_argument(
        "--copy",
        dest="mode",
        action="store_const",
        const="copy",
        help="Copy files; on re-runs skip files whose size and mtime already match.",
    )
    mode.add_argument(
        "--force-copy",
        dest="mode",
        action="store_const",
        const="force-copy",
        help="Always copy and overwrite, regardless of existing target state.",
    )
    sync_p.set_defaults(mode="hardlink")
    sync_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done, don't change anything on disk.",
    )
    sync_p.add_argument(
        "--delete",
        action="store_true",
        help="Remove stray folders from the target library.",
    )
    sync_p.add_argument(
        "--create",
        action="store_true",
        help="Create the target library directory if it doesn't exist.",
    )

    diff_p = sub.add_parser(
        "diff",
        parents=[common],
        help="Compare source and target libraries without writing anything.",
    )
    _add_io_args(diff_p)

    plan_p = sub.add_parser(
        "plan",
        parents=[common],
        help="Show the Plan a sync would execute, without touching the target.",
    )
    _add_io_args(plan_p)

    return parser


def _add_io_args(p: argparse.ArgumentParser) -> None:
    format_choices = [
        jp.JellyfinLibraryReader.shortname(),
        jp.PlexLibraryReader.shortname(),
        "auto",
    ]
    p.add_argument("source", help="Source media library path.")
    p.add_argument("target", help="Target media library path.")
    p.add_argument(
        "--source-format",
        type=str,
        choices=format_choices,
        default="auto",
        help="Source library format ('auto' detects from the source layout).",
    )
    p.add_argument(
        "--target-format",
        type=str,
        choices=format_choices,
        default="auto",
        help="Target library format ('auto' picks the opposite of the source).",
    )


def _inject_default_subcommand(argv: list[str]) -> list[str]:
    """If the first positional argument isn't a known subcommand, treat the
    call as `sync ...`. Keeps the historical invocation `jellyplex-sync
    <source> <target>` working alongside the new `jellyplex-sync sync ...`.
    """
    if not argv:
        return argv
    first = argv[0]
    if first.startswith("-"):
        return argv
    if first in _SUBCOMMANDS:
        return argv
    return ["sync", *argv]


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args(_inject_default_subcommand(sys.argv[1:]))

    # Under --json, INFO chatter on stderr distracts from the JSON document
    # on stdout. Quiet stderr to WARNING by default; --verbose or --debug
    # explicitly opt back in.
    if args.debug:
        level = logging.DEBUG
    elif args.json and not args.verbose:
        level = logging.WARNING
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(levelname)s: %(asctime)s -- %(message)s",
    )

    if args.command == "sync":
        result = _do_sync(args)
    elif args.command == "diff":
        result = _do_diff(args)
    elif args.command == "plan":
        result = _do_plan(args)
    else:
        parser.error(f"unknown command: {args.command!r}")
        result = 2
    sys.exit(result)


def _do_sync(args: argparse.Namespace) -> int:
    import pathlib

    from jellyplex_sync.library import CollectingReporter
    from jellyplex_sync.sync import LibraryStats

    materializer = _make_materializer(args.mode)
    stats = LibraryStats() if args.json else None
    reporter = CollectingReporter() if args.json else None
    try:
        rc = jp.sync(
            args.source,
            args.target,
            dry_run=args.dry_run,
            delete=args.delete,
            create=args.create,
            verbose=args.verbose,
            debug=args.debug,
            source_format=args.source_format,
            target_format=args.target_format,
            materializer=materializer,
            reporter=reporter,
            stats=stats,
        )
    except KeyboardInterrupt:
        logging.info("INTERRUPTED")
        return 10
    except Exception as exc:
        logging.error("Exception: %s", exc)
        return 99

    if args.json:
        assert stats is not None and reporter is not None
        source_short, target_short = _resolve_formats_for_json(args)
        from jellyplex_sync.json_output import write_sync_json

        write_sync_json(
            sys.stdout,
            source_path=pathlib.Path(args.source),
            source_format=source_short,
            target_path=pathlib.Path(args.target),
            target_format=target_short,
            dry_run=args.dry_run,
            exit_code=rc,
            stats=stats,
            drops=reporter.drops,
        )
    return rc


def _make_materializer(mode: str) -> jp.FileMaterializer:
    if mode == "hardlink":
        return jp.HardlinkMaterializer()
    if mode == "copy":
        return jp.CopyMaterializer()
    if mode == "force-copy":
        return jp.ForceCopyMaterializer()
    raise ValueError(f"unknown materialization mode: {mode!r}")


def _do_diff(args: argparse.Namespace) -> int:
    from jellyplex_sync.sync import diff

    try:
        return diff(
            args.source,
            args.target,
            debug=args.debug,
            source_format=args.source_format,
            target_format=args.target_format,
            as_json=args.json,
        )
    except KeyboardInterrupt:
        logging.info("INTERRUPTED")
        return 10
    except Exception as exc:
        logging.error("Exception: %s", exc)
        return 99


def _do_plan(args: argparse.Namespace) -> int:
    from jellyplex_sync.sync import plan as plan_fn

    try:
        return plan_fn(
            args.source,
            args.target,
            debug=args.debug,
            source_format=args.source_format,
            target_format=args.target_format,
            as_json=args.json,
        )
    except KeyboardInterrupt:
        logging.info("INTERRUPTED")
        return 10
    except Exception as exc:
        logging.error("Exception: %s", exc)
        return 99


def _resolve_formats_for_json(args: argparse.Namespace) -> tuple[str, str]:
    """Re-run the same format resolution `sync()` did so the JSON payload
    reports the formats that were actually used. Returns ('?', '?') if
    resolution fails — sync() will already have logged the error and the
    caller's exit code reflects it."""
    import pathlib

    from jellyplex_sync.sync import _resolve_formats

    resolved = _resolve_formats(
        pathlib.Path(args.source), args.source_format, args.target_format
    )
    return resolved if resolved else ("?", "?")


if __name__ == "__main__":
    main()
