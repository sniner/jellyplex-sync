#!/usr/bin/python3

import argparse
import logging
import os
import sys

import jellyplex as jp


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
    parser.add_argument("--update-filenames", action="store_true", help="Rename existing hardlinks if they have outdated names")
    parser.add_argument("--verify-only", action="store_true", help="Check all existing hard links without making changes, report any broken links")
    parser.add_argument("--skip-verify", action="store_true", help="Skip inode verification for faster syncs when you trust existing links")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--partial", help="Sync only the specified movie folder path")
    group.add_argument("--radarr-hook", action="store_true", help="Read movie path from Radarr environment variables")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s: %(asctime)s -- %(message)s",
    )

    partial_path = args.partial

    if args.radarr_hook:
        event_type = os.environ.get("radarr_eventtype")
        if event_type is None:
            logging.error("radarr_eventtype environment variable not set")
            sys.exit(1)

        if event_type == "Test":
            logging.info("Radarr connection test successful")
            sys.exit(0)

        if event_type not in ["Download", "Upgrade", "Rename"]:
            logging.info(f"Ignoring Radarr event type: {event_type}")
            sys.exit(0)

        radarr_path = os.environ.get("radarr_movie_path")
        if not radarr_path:
            logging.error("radarr_movie_path environment variable not set")
            sys.exit(1)

        movie_title = os.environ.get("radarr_movie_title", "Unknown")
        logging.info(f"Radarr hook triggered for movie: {movie_title}")
        partial_path = radarr_path

    result = 0
    try:
        result = jp.sync(
            args.source,
            args.target,
            dry_run=args.dry_run,
            delete=args.delete,
            create=args.create,
            verbose=args.verbose,
            debug=args.debug,
            convert_to=args.convert_to,
            update_filenames=args.update_filenames,
            partial_path=partial_path,
            verify_only=args.verify_only,
            skip_verify=args.skip_verify,
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
