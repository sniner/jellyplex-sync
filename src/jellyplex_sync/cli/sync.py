#!/usr/bin/python3

import argparse
import logging
import pathlib
import sys

import jellyplex_sync as jp


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Plex compatible media library from a Jellyfin library.")
    parser.add_argument("source", help="Jellyfin media library")
    parser.add_argument("target", help="Plex media library")
    parser.add_argument("--convert-to", type=str,
        choices=[jp.JellyfinLibrary.shortname(), jp.PlexLibrary.shortname(), "auto"], default="auto",
        help="Type of library to convert to ('auto' will try to determine source library type)")
    parser.add_argument("--dry-run", action="store_true", help="Show actions only, don't execute them")
    parser.add_argument("--delete", action="store_true", help="Remove stray folders from target library")
    parser.add_argument("--create", action="store_true", help="Create missing target library")
    parser.add_argument("--verbose", action="store_true", help="Show more information messages")
    parser.add_argument("--debug", action="store_true", help="Show debug messages")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s: %(asctime)s -- %(message)s",
    )

    result = 0
    try:
        result = jp.sync(
            args.source,
            args.target,
            dry_run= args.dry_run,
            delete=args.delete,
            create=args.create,
            verbose=args.verbose,
            debug=args.debug,
            convert_to=args.convert_to,
        )
    except KeyboardInterrupt:
        logging.info("INTERRUPTED")
        result = 10
    except Exception as exc:
        logging.error("Exception: %s", exc)
        result = 99
    sys.exit(result)


if __name__ == "__main__":
    main()
