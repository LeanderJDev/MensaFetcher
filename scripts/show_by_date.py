#!/usr/bin/env python3
"""Show snapshot entries for given tag(s).

Examples:
  python3 scripts/show_by_tag.py --tag V --tag vg --days 7
  python3 scripts/show_by_tag.py --tag V --from 2026-01-01 --to 2026-01-07 --csv out.csv
"""

from __future__ import annotations

import argparse
import csv
import datetime
import sqlite3
import sys
from typing import List, Optional, Tuple


def parse_date_range(
    from_s: Optional[str], to_s: Optional[str], days: Optional[int]
) -> Tuple[Optional[str], Optional[str]]:
    if days is not None and days > 0:
        today = datetime.date.today()
        start = (today - datetime.timedelta(days=days - 1)).isoformat()
        end = today.isoformat()
        return start, end
    if from_s and to_s:
        return from_s, to_s
    if from_s and not to_s:
        return from_s, None
    if to_s and not from_s:
        return None, to_s
    return None, None


def print_table(headers: List[str], rows: List[List[str]]) -> None:
    col_widths = [len(h) for h in headers]
    for r in rows:
        for i, v in enumerate(r):
            col_widths[i] = max(col_widths[i], len(v))

    hdr = " | ".join(headers[i].ljust(col_widths[i]) for i in range(len(headers)))
    sep = "-+-".join("-" * w for w in col_widths)
    print(hdr)
    print(sep)
    for r in rows:
        print(" | ".join(r[i].ljust(col_widths[i]) for i in range(len(headers))))


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Show snapshot entries filtered by tag code(s)"
    )
    p.add_argument("--db", default="mensa.db", help="Path to sqlite DB file")
    p.add_argument(
        "--tag", action="append", help="Tag code to filter (repeatable)"
    )  # Hier war GH CP verwirrt vom deutschen Tag und den Tagen
    p.add_argument("--from", dest="from_date", help="Start date (inclusive) YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", help="End date (inclusive) YYYY-MM-DD")
    p.add_argument(
        "--days", type=int, help="Show last N days (overrides --from/--to if set)"
    )
    p.add_argument("--csv", help="Write CSV to provided path instead of pretty table")
    args = p.parse_args(argv)

    tags: List[str] = []
    if args.tag:
        for t in args.tag:
            # accept comma-separated lists too
            tags += [x.strip() for x in t.split(",") if x.strip()]

    start, end = parse_date_range(args.from_date, args.to_date, args.days)

    try:
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        print(f"Failed to open DB '{args.db}': {e}", file=sys.stderr)
        return 3

    cur = conn.cursor()

    placeholders = ",".join(["?"] * len(tags))
    q = (
        "SELECT s.id as snapshot_id, s.date, s.attempt, s.created_at, s.empties_count, "
        "se.category, se.price_eur, se.went_empty, "
        "d.id as dish_id, d.name as dish_name, d.description as dish_description, t.code as tag_code "
        "FROM snapshot_entry se "
        "JOIN snapshot s ON s.id = se.snapshot_id "
        "JOIN dish d ON d.id = se.dish_id "
        "JOIN dish_tag dt ON dt.dish_id = d.id "
        "JOIN tag t ON t.id = dt.tag_id "
        f"WHERE t.code IN ({placeholders}) "
    )

    params: List[str] = tags[:]
    if start:
        q += " AND s.date >= ?"
        params.append(start)
    if end:
        q += " AND s.date <= ?"
        params.append(end)

    q += " ORDER BY s.date DESC, s.attempt DESC, d.name"

    cur.execute(q, params)
    rows = cur.fetchall()

    if not rows:
        print("No entries found for the given tag(s) / date range.")
        return 0

    out_rows: List[List[str]] = []
    for r in rows:
        out_rows.append(
            [
                str(r["snapshot_id"]),
                r["date"],
                str(r["attempt"]),
                r["created_at"],
                str(r["empties_count"] or ""),
                r["category"] or "",
                f"{r['price_eur']:.2f}" if r["price_eur"] is not None else "",
                "1" if r["went_empty"] else "0",
                str(r["dish_id"]),
                r["dish_name"] or "",
                (r["dish_description"] or "").replace("\n", " "),
                r["tag_code"] or "",
            ]
        )

    headers = [
        "snapshot_id",
        "date",
        "attempt",
        "created_at",
        "empties_count",
        "category",
        "price_eur",
        "went_empty",
        "dish_id",
        "dish_name",
        "dish_description",
        "tag_code",
    ]

    if args.csv:
        try:
            with open(args.csv, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(headers)
                for r in out_rows:
                    writer.writerow(r)
            print(f"Wrote {len(out_rows)} rows to {args.csv}")
        except Exception as e:
            print(f"Failed to write CSV: {e}", file=sys.stderr)
            return 4
    else:
        print_table(headers, out_rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
