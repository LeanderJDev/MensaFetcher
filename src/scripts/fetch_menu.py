#!/usr/bin/env python3
"""
Wrapper script for mensa/parser.py to fetch and parse a mensa menu HTML page.

Usage examples:
  python3 parse_menu.py --file sample_menu.html
  python3 parse_menu.py --url https://example.my-mensa.de/essen.php

"""

import argparse
import datetime
import re
import os
import sys
import tempfile
import json

from .. import parser


def main() -> None:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--file", help="Read HTML from file")
    arg_parser.add_argument("--url", help="Fetch HTML from URL")
    arg_parser.add_argument("--date", help="Fetch HTML from URL for specific date")
    arg_parser.add_argument(
        "--output", "-o", default=None, help="Output JSON file (default: stdout)"
    )
    args = arg_parser.parse_args()
    if not args.file and not args.url:
        arg_parser.error("provide --file or --url")

    # Normalize date token for parsing and for filename when requested.
    date = args.date
    if date == "today":
        today = datetime.date.today()
        day_of_year = today.timetuple().tm_yday
        date = str(today.year * 1000 + day_of_year)

    # If the user didn't override the output filename and provided a date,
    # derive a filename using that date (sanitized). If no output is given,
    # default behavior is to write JSON to stdout.
    output_filename = args.output
    if args.date and not output_filename:
        safe_date = re.sub(r"[^A-Za-z0-9_.-]", "_", date)
        output_filename = f"menu_{safe_date}.json"

    if args.file:
        html = parser.load_html_from_file(args.file)
    else:
        html = parser.load_html_from_url(args.url)

    parsed = parser.parse_html(html, date)

    # If an output filename was provided (or derived from date), write
    # atomically to that file. Otherwise print JSON to stdout.
    if output_filename:
        # --- Atomarer Schreibvorgang ---
        out_dir = os.path.dirname(output_filename) or "."
        fd, tmp_path = tempfile.mkstemp(prefix="tmp_menu_", dir=out_dir, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tf:
                json.dump(parsed, tf, ensure_ascii=False, indent=2)
                tf.flush()
                os.fsync(tf.fileno())
            # atomar ersetzen
            os.replace(tmp_path, output_filename)
        except Exception:
            # Aufräumen bei Fehlern
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            raise

        print(f"Wrote {len(parsed)} items to {output_filename}")
    else:
        # default: print JSON to stdout
        json_text = json.dumps(parsed, ensure_ascii=False, indent=2)
        sys.stdout.write(json_text + "\n")


if __name__ == "__main__":
    main()
