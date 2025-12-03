#!/usr/bin/env python3
"""Ingest parsed menu items into a normalized SQLite database.

This script is intended to be called from cron twice daily (attempt 1 and 2).
It calls the parser, upserts dishes/tags and snapshot entries, and when
running the second attempt computes which dishes went empty.

Usage examples:
  python3 -m src.ingest --url 'https://freiberg.my-mensa.de/essen.php?lang=de&mensa=freiberg' --attempt 1
  python3 -m src.ingest --url 'https://freiberg.my-mensa.de/essen.php?lang=de&mensa=freiberg' --attempt 2 --notify-cmd '/usr/bin/notify-send'

Notification on error: set environment variable `MENSA_NOTIFY_CMD` or pass
`--notify-cmd` to run a small handler with subject and body as args.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sqlite3
import subprocess
import sys
import trace
import traceback
from typing import Optional

from src import parser
from src import db as dbmod


def parse_date_arg(date_str: Optional[str]) -> datetime.date:
    """Convert a user-provided date argument into a datetime.date.

    Accepts `None`, `today`, `now` or an ISO date string (`YYYY-MM-DD`).

    Args:
        date_str: optional date string from CLI

    Returns:
        a `datetime.date` instance representing the requested date.
    """
    if not date_str or date_str in ("today", "now"):
        return datetime.date.today()
    return datetime.date.fromisoformat(date_str)


def notify_if_configured(cmd: Optional[str], subject: str, body: str) -> None:
    """Invoke a notification command if configured.

    The function first uses the explicitly provided `cmd` argument, if any,
    otherwise it falls back to the `MENSA_NOTIFY_CMD` environment variable.
    The command is executed with `subject` and `body` as positional
    arguments. Failures are intentionally non-fatal and only logged to stderr.

    Args:
        cmd: optional command to execute (string). If None, `MENSA_NOTIFY_CMD` is used.
        subject: short subject passed as first argument to the command
        body: longer body passed as second argument to the command
    """
    if not cmd:
        cmd = os.environ.get("MENSA_NOTIFY_CMD")
    if not cmd:
        return
    try:
        # run command as a shell invocation if it contains spaces; allow
        # user to pass e.g. '/usr/bin/notify-send' or 'sh /path/to/script.sh'
        subprocess.run([cmd, subject, body], check=False)
    except Exception:
        print("Notification failed", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)


def main() -> None:
    """CLI entry point for ingesting a menu into the SQLite DB.

    Typical usage is to call this script twice per day from cron with
    `--attempt 1` and `--attempt 2`. On the second attempt the script
    computes which dishes went empty and may optionally notify.
    """
    p = argparse.ArgumentParser(description="Ingest mensa menu into SQLite DB")
    p.add_argument("--url", required=True, help="URL to fetch menu from")
    p.add_argument("--db", default="mensa.db", help="Path to sqlite database file")
    p.add_argument(
        "--date",
        default=None,
        help="Date token (YYYY-MM-DD or tag id). Defaults to today",
    )
    p.add_argument(
        "--attempt",
        required=True,
        type=int,
        choices=[1, 2],
        help="1 (first fetch) or 2 (second fetch)",
    )
    p.add_argument(
        "--notify-cmd",
        default=None,
        help="Optional notify command to run on error/special events",
    )
    args = p.parse_args()

    conn = None
    try:
        date_token = parse_date_arg(args.date)

        conn = sqlite3.connect(args.db, timeout=10.0)

        # recommended pragmas for cron usage
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")

        dbmod.init_db(conn)

        # parse the page for the requested date token
        items, tags = parser.parse_url_to_items(args.url, date_token)

        # store snapshot and related data
        snapshot_id = dbmod.store_snapshot(
            conn, date_token, args.attempt, items, tags, source_url=args.url
        )
        print(
            f"Stored snapshot {snapshot_id} with {len(items)} items (date={date_token}, attempt={args.attempt})"
        )

        if args.attempt == 2:
            empties = dbmod.compute_empties(conn, date_token)
            print(f"Found {len(empties)} items that went empty since attempt=1")

    except Exception:
        tb = traceback.format_exc()
        print("Error during ingest:\n", tb, file=sys.stderr)
        # try to notify, but don't let notification failures mask the original error
        try:
            notify_if_configured(args.notify_cmd, "Mensa ingest failed", tb)
        except Exception as nerr:
            print("Notification failed:", nerr, file=sys.stderr)
        # exit non-zero so cron detects failure; avoid re-raising to prevent
        # duplicate tracebacks and ensure cleanup runs below
        sys.exit(1)
    finally:
        # only commit/close if connection was created
        if conn is not None:
            try:
                conn.commit()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
