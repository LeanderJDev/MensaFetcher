"""Small helper utilities for analyzing MensaFetcher SQLite snapshots.

These helpers provide a consistent DB connection (PRAGMAs) and convenient
exports into pandas DataFrames for notebook analysis and plotting.

Usage examples:
    from scripts.analysis_utils import open_conn, list_snapshots, export_snapshot_to_pandas
    conn = open_conn('data/mensa_260511.db')
    print(list_snapshots(conn))
    df = export_snapshot_to_pandas(conn, snapshot_id=1)

"""

from __future__ import annotations

import sqlite3
from typing import List, Dict, Any, Optional

import pandas as pd


def open_conn(db_path: str) -> sqlite3.Connection:
    """Open sqlite3 connection and set recommended PRAGMAs used by the project.

    Returns a Connection with `row_factory` set to sqlite3.Row.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA busy_timeout = 5000;")
    return conn


def list_snapshots(
    conn: sqlite3.Connection, limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Return a list of snapshots ordered by date, attempt."""
    q = "SELECT id, date, attempt, created_at, empties_count, computed_at FROM snapshot ORDER BY date, attempt"
    if limit:
        q = q + " LIMIT ?"
        rows = conn.execute(q, (limit,)).fetchall()
    else:
        rows = conn.execute(q).fetchall()
    return [dict(r) for r in rows]


def get_snapshot_entries(
    conn: sqlite3.Connection, snapshot_id: int
) -> List[Dict[str, Any]]:
    """Return snapshot entries with dish fields and a comma separated tag list."""
    q = """
    SELECT se.snapshot_id, se.dish_id, d.canonical_hash, d.name, d.description, se.category, se.price_eur, se.went_empty,
      (SELECT GROUP_CONCAT(t.code, ',') FROM dish_tag dt JOIN tag t ON dt.tag_id = t.id WHERE dt.dish_id = d.id) AS tags
    FROM snapshot_entry se
    JOIN dish d ON se.dish_id = d.id
    WHERE se.snapshot_id = ?
    ORDER BY se.category, d.name
    """
    rows = conn.execute(q, (snapshot_id,)).fetchall()
    return [dict(r) for r in rows]


def export_snapshot_to_pandas(
    conn: sqlite3.Connection, snapshot_id: int
) -> pd.DataFrame:
    """Export a snapshot into a pandas DataFrame.

    Columns: snapshot_id, dish_id, canonical_hash, name, description, category, price_eur, went_empty, tags
    """
    rows = get_snapshot_entries(conn, snapshot_id)
    if not rows:
        return pd.DataFrame(
            columns=[
                "snapshot_id",
                "dish_id",
                "canonical_hash",
                "name",
                "description",
                "category",
                "price_eur",
                "went_empty",
                "tags",
            ]
        )
    df = pd.DataFrame(rows)
    # normalize tags into lists for convenience
    df["tags"] = df["tags"].fillna("").apply(lambda s: s.split(",") if s else [])
    return df


def get_dish_timeseries(conn: sqlite3.Connection, dish_identifier: Any) -> pd.DataFrame:
    """Return a timeseries for a dish identified by id or canonical_hash.

    The returned DataFrame has columns: date, attempt, price_eur, went_empty, snapshot_id
    """
    if isinstance(dish_identifier, int):
        cond = "d.id = ?"
        param = (dish_identifier,)
    else:
        cond = "d.canonical_hash = ?"
        param = (dish_identifier,)

    q = f"""
    SELECT s.date, s.attempt, se.price_eur, se.went_empty, s.id as snapshot_id
    FROM snapshot_entry se
    JOIN snapshot s ON se.snapshot_id = s.id
    JOIN dish d ON se.dish_id = d.id
    WHERE {cond}
    ORDER BY s.date, s.attempt
    """
    rows = conn.execute(q, param).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    return df
