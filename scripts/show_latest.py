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
    p = argparse.ArgumentParser(
        description="Show newest snapshot_entries and snapshots from MensaFetcher DB"
    )
    p.add_argument("--db", default="mensa.db", help="Path to sqlite DB file")
    p.add_argument(
        "--entry-limit",
        type=int,
        default=50,
        help="Limit number of newest snapshot_entries shown (0 = all)",
    )
    p.add_argument(
        "--snapshot-limit",
        type=int,
        default=10,
        help="Limit number of newest snapshots shown (0 = all)",
    )
    args = p.parse_args(argv)

    try:
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        print(f"Failed to open DB '{args.db}': {e}", file=sys.stderr)
        return 2

    cur = conn.cursor()

    # Fetch newest snapshot_entries (joined with snapshot and dish data)
    entry_limit = args.entry_limit
    entry_q = (
        "SELECT se.snapshot_id, s.date as snapshot_date, s.attempt as snapshot_attempt, "
        "s.created_at as snapshot_created_at, s.empties_count, se.category, se.price_eur, se.went_empty, "
        "d.id as dish_id, d.name as dish_name, d.description as dish_description, "
        "(SELECT GROUP_CONCAT(t.code, ',') FROM dish_tag dt JOIN tag t ON t.id = dt.tag_id WHERE dt.dish_id = d.id) as tags "
        "FROM snapshot_entry se "
        "JOIN snapshot s ON s.id = se.snapshot_id "
        "JOIN dish d ON d.id = se.dish_id "
        "ORDER BY s.created_at DESC, se.snapshot_id DESC"
    )

    if entry_limit and entry_limit > 0:
        entry_q = entry_q + f" LIMIT {int(entry_limit)}"

    cur.execute(entry_q)
    entries = cur.fetchall()

    # Print entries as a table
    def print_table(headers, rows):
        # simple column width calc and printing
        cols = len(headers)
        col_widths = [len(h) for h in headers]
        str_rows = []
        for r in rows:
            sr = ["" if v is None else str(v) for v in r]
            str_rows.append(sr)
            for i, v in enumerate(sr):
                col_widths[i] = max(col_widths[i], len(v))

        # header
        hdr = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
        sep = "-+-".join("-" * w for w in col_widths)
        print(hdr)
        print(sep)
        for sr in str_rows:
            print(" | ".join(sr[i].ljust(col_widths[i]) for i in range(cols)))

    if entries:
        print("Newest snapshot_entries:")
        # build rows for table
        e_rows = []
        for r in entries:
            e_rows.append(
                [
                    r["snapshot_id"],
                    r["snapshot_date"],
                    r["snapshot_attempt"],
                    r["snapshot_created_at"],
                    r["empties_count"],
                    r["category"] or "",
                    f"{r['price_eur']:.2f}" if r["price_eur"] is not None else "",
                    "1" if r["went_empty"] else "0",
                    r["dish_id"],
                    r["dish_name"],
                    (r["dish_description"] or "").replace("\n", " "),
                    r["tags"] or "",
                ]
            )

        headers = [
            "snapshot_id",
            "date",
            "attempt",
            "snapshot_created_at",
            "empties_count",
            "category",
            "price_eur",
            "went_empty",
            "dish_id",
            "dish_name",
            "dish_description",
            "tags",
        ]
        print_table(headers, e_rows)
    else:
        print("No snapshot_entries found.")

    # Fetch newest snapshots
    snap_limit = args.snapshot_limit
    snap_q = "SELECT id, date, attempt, created_at, empties_count, computed_at FROM snapshot ORDER BY created_at DESC"
    if snap_limit and snap_limit > 0:
        snap_q = snap_q + f" LIMIT {int(snap_limit)}"
    cur.execute(snap_q)
    snaps = cur.fetchall()
    print()
    if snaps:
        print("Newest snapshots:")
        s_rows = []
        for s in snaps:
            s_rows.append(
                [
                    s["id"],
                    s["date"],
                    s["attempt"],
                    s["created_at"],
                    s["empties_count"],
                    s["computed_at"] or "",
                ]
            )
        s_headers = [
            "id",
            "date",
            "attempt",
            "created_at",
            "empties_count",
            "computed_at",
        ]
        print_table(s_headers, s_rows)
    else:
        print("No snapshots found.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
