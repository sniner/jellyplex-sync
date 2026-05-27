#!/usr/bin/python3
"""Backward-compatible ``jellyplex-sync`` entry point.

Provides the same interface as the original single-command CLI: flat
argument list, no subcommands.
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys

import jellyplex_sync as jp


def _build_parser() -> argparse.ArgumentParser:
    format_choices = [
        jp.JellyfinLibraryReader.shortname(),
        jp.PlexLibraryReader.shortname(),
        "auto",
    ]

    parser = argparse.ArgumentParser(
        prog="jellyplex-sync",
        description="Mirror a source library into the target layout.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show more information messages.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show debug messages.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON document on stdout. Logs continue to go to stderr.",
    )
    parser.add_argument("source", help="Source media library path.")
    parser.add_argument("target", help="Target media library path.")
    parser.add_argument(
        "--source-format",
        type=str,
        choices=format_choices,
        default="auto",
        help="Source library format ('auto' detects from the source layout).",
    )
    parser.add_argument(
        "--target-format",
        type=str,
        choices=format_choices,
        default="auto",
        help="Target library format ('auto' picks the opposite of the source).",
    )

    mode = parser.add_mutually_exclusive_group()
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
    parser.set_defaults(mode="hardlink")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done, don't change anything on disk.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Remove stray folders from the target library.",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="Create the target library directory if it doesn't exist.",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

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

    if args.mode == "hardlink":
        materializer: jp.FileMaterializer = jp.HardlinkMaterializer()
    elif args.mode == "copy":
        materializer = jp.CopyMaterializer()
    elif args.mode == "force-copy":
        materializer = jp.ForceCopyMaterializer()
    else:
        raise ValueError(f"unknown materialization mode: {args.mode!r}")

    from jellyplex_sync.library import CollectingReporter
    from jellyplex_sync.sync import LibraryStats

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
        sys.exit(10)
    except Exception as exc:
        logging.error("Exception: %s", exc)
        sys.exit(99)

    if args.json:
        assert stats is not None and reporter is not None
        from jellyplex_sync.json_output import write_sync_json
        from jellyplex_sync.sync import _resolve_formats

        resolved = _resolve_formats(
            pathlib.Path(args.source),
            args.source_format,
            args.target_format,
        )
        source_short, target_short = resolved if resolved else ("?", "?")

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

    sys.exit(rc)


if __name__ == "__main__":
    main()
