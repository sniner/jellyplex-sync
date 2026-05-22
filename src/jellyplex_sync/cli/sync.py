#!/usr/bin/python3
from __future__ import annotations

import argparse
import logging
import sys

import jellyplex_sync as jp

_SUBCOMMANDS = {"sync", "diff"}


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
        help="Compare source and target libraries (not yet implemented).",
    )
    _add_io_args(diff_p)

    return parser


def _add_io_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("source", help="Source media library path.")
    p.add_argument("target", help="Target media library path.")
    p.add_argument(
        "--convert-to",
        type=str,
        choices=[
            jp.JellyfinLibraryReader.shortname(),
            jp.PlexLibraryReader.shortname(),
            "auto",
        ],
        default="auto",
        help="Target format ('auto' tries to detect from the source).",
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

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s: %(asctime)s -- %(message)s",
    )

    if args.command == "sync":
        result = _do_sync(args)
    elif args.command == "diff":
        result = _do_diff(args)
    else:
        parser.error(f"unknown command: {args.command!r}")
        result = 2
    sys.exit(result)


def _do_sync(args: argparse.Namespace) -> int:
    materializer = _make_materializer(args.mode)
    try:
        return jp.sync(
            args.source,
            args.target,
            dry_run=args.dry_run,
            delete=args.delete,
            create=args.create,
            verbose=args.verbose,
            debug=args.debug,
            convert_to=args.convert_to,
            materializer=materializer,
        )
    except KeyboardInterrupt:
        logging.info("INTERRUPTED")
        return 10
    except Exception as exc:
        logging.error("Exception: %s", exc)
        return 99


def _make_materializer(mode: str) -> jp.FileMaterializer:
    if mode == "hardlink":
        return jp.HardlinkMaterializer()
    if mode == "copy":
        return jp.CopyMaterializer()
    if mode == "force-copy":
        return jp.ForceCopyMaterializer()
    raise ValueError(f"unknown materialization mode: {mode!r}")


def _do_diff(args: argparse.Namespace) -> int:
    # Wired up in a later step of Paket 4; this just announces itself for now
    # so the subcommand surface is testable.
    logging.error("`diff` is not implemented yet; coming in a follow-up commit.")
    return 2


if __name__ == "__main__":
    main()
