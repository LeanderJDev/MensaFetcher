#!/usr/bin/env python3
"""
Stores parsed menu items from a given URL into a database

Should be called from cron

Usage:
    python3 -m src.ingest--url https://example.my-mensa.de/essen.php
"""

import argparse
import datetime
from src import parser
import json
import os


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True, help="URL to fetch menu from")
    p.add_argument("--count", type=int, default=0, help="# of fetch for same day")
    args = p.parse_args()

    date = datetime.date.today()

    items = parser.parse_url_to_items(args.url, date)

    # beispiel: wenn kein output angegeben, benenne nach datum
    out = args.output or f"menu_{date}.json"
    with open(out + ".tmp", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(out + ".tmp", out)
    print(f"Wrote {len(items)} items to {out}")


if __name__ == "__main__":
    main()
