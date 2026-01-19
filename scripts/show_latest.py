#!/usr/bin/env python3
"""Show latest snapshot entries from MensaFetcher SQLite DB in readable form.

Usage: python3 scripts/show_latest.py [--db PATH] [--limit N]
Default DB path: mensa.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import Optional


def format_row(row: sqlite3.Row) -> str:
    tags = row["tags"] or ""
    went_empty = "(EMPTY)" if row["went_empty"] else ""
    price = f"{row['price_eur']:.2f}€" if row["price_eur"] is not None else "-"
    desc = row["description"] or ""
    lines = [f"- {row['category'] or 'Allg.'} | {row['name']} — {price} {went_empty}"]
    if tags:
        lines[0] += f" [{tags}]"
    if desc:
        lines.append(f"    {desc}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Show latest MensaFetcher snapshot entries")
    p.add_argument("--db", default="mensa.db", help="Path to sqlite DB file")
    p.add_argument(
        "--limit", type=int, default=0, help="Limit number of rows shown (0 = all)"
    )
    args = p.parse_args(argv)

    try:
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        print(f"Failed to open DB '{args.db}': {e}", file=sys.stderr)
        return 2

    cur = conn.cursor()

    cur.execute(
        "SELECT id, date, attempt, created_at FROM snapshot ORDER BY created_at DESC LIMIT 1"
    )
    snap = cur.fetchone()
    if not snap:
        print("No snapshots found in DB.")
        return 0

    snap_id = snap["id"]
    print(
        f"Latest snapshot: id={snap_id}, date={snap['date']}, attempt={snap['attempt']}, created_at={snap['created_at']}"
    )
    print("Entries:")

    q = (
        "SELECT se.category, se.price_eur, se.went_empty, d.id as dish_id, d.name, d.description, "
        "GROUP_CONCAT(t.code, ',') as tags "
        "FROM snapshot_entry se "
        "JOIN dish d ON d.id = se.dish_id "
        "LEFT JOIN dish_tag dt ON dt.dish_id = d.id "
        "LEFT JOIN tag t ON t.id = dt.tag_id "
        "WHERE se.snapshot_id = ? "
        "GROUP BY d.id "
        "ORDER BY se.category IS NULL, se.category, d.name"
    )

    cur.execute(q, (snap_id,))
    rows = cur.fetchall()
    if not rows:
        print(" (no entries)")
        return 0

    limit = args.limit or len(rows)
    for i, r in enumerate(rows[:limit]):
        print(format_row(r))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
