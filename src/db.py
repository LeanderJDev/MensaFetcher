"""Database helpers for MensaFetcher.

Provides initialization and core functions:
- init_db(conn)
- store_snapshot(conn, date_token, attempt, items, source_url=None)
- compute_empties(conn, date_token) -> List[dict]

The schema is normalized: dish, tag, dish_tag, snapshot, snapshot_entry, daily_empty
"""

from __future__ import annotations

import json
import sqlite3
from hashlib import sha1
from typing import Any, Dict, Iterable, List, Optional


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize database schema and perform simple migrations.

    Creates the normalized tables used by the ingest pipeline if they do
    not already exist. This function is idempotent and safe to call on an
    existing database; it only creates missing tables/indices.

    Args:
        conn: an open sqlite3.Connection where the schema will be ensured.
    """
    cur = conn.cursor()
    cur.executescript(
        """
BEGIN;

CREATE TABLE IF NOT EXISTS dish (
    id INTEGER PRIMARY KEY,
    canonical_hash TEXT UNIQUE NOT NULL,
    name TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS tag (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  name TEXT
);

CREATE TABLE IF NOT EXISTS dish_tag (
  dish_id INTEGER NOT NULL,
  tag_id INTEGER NOT NULL,
  PRIMARY KEY (dish_id, tag_id),
  FOREIGN KEY (dish_id) REFERENCES dish(id),
  FOREIGN KEY (tag_id) REFERENCES tag(id)
);

CREATE TABLE IF NOT EXISTS snapshot (
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    empties_count INTEGER DEFAULT 0,
    computed_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_snapshot_date_attempt ON snapshot(date, attempt);

CREATE TABLE IF NOT EXISTS snapshot_entry (
  snapshot_id INTEGER NOT NULL,
  dish_id INTEGER NOT NULL,
  category TEXT,
  price_eur REAL,
  went_empty INTEGER DEFAULT 0,
  PRIMARY KEY (snapshot_id, dish_id),
  FOREIGN KEY (snapshot_id) REFERENCES snapshot(id),
  FOREIGN KEY (dish_id) REFERENCES dish(id)
);

COMMIT;
"""
    )
    conn.commit()


def _canonical_hash_for_item(item: Dict[str, Any]) -> str:
    """Return a stable canonical hash for a dish item.

    The canonical hash is derived from the dish name, description and
    sorted tag list. It is used as a stable identifier to deduplicate
    dishes across snapshots. The function returns a hex SHA1 digest.

    Args:
        item: dictionary with at least `name`, optional `description` and `tags`.

    Returns:
        hex string of the SHA1 digest.
    """
    name = (item.get("name") or "").strip().lower()
    description = (item.get("description") or "").strip().lower()
    tags = sorted(item.get("tags") or [])
    key = f"{name}|{description}|{','.join(tags)}"
    return sha1(key.encode("utf-8")).hexdigest()


def _upsert_dish(conn: sqlite3.Connection, item: Dict[str, Any]) -> int:
    """Insert or update a `dish` row and return its id.

    Uses the canonical hash to detect existing dishes. If the dish already
    exists the `name` and `description` fields are updated.

    Args:
        conn: sqlite3.Connection
        item: parsed dish dictionary (expects `name` and `description` keys)

    Returns:
        integer primary key of the dish row.
    """
    ch = _canonical_hash_for_item(item)
    cur = conn.cursor()
    cur.execute("SELECT id FROM dish WHERE canonical_hash = ?", (ch,))
    row = cur.fetchone()
    if row:
        dish_id = row[0]
        # Optionally update name/description/category if changed
        cur.execute(
            "UPDATE dish SET name = ?, description = ? WHERE id = ?",
            (item.get("name"), item.get("description"), dish_id),
        )
        return dish_id
    cur.execute(
        "INSERT INTO dish (canonical_hash, name, description) VALUES (?, ?, ?)",
        (ch, item.get("name"), item.get("description")),
    )
    return cur.lastrowid


def _upsert_tags(conn: sqlite3.Connection, tags: Dict[str, str]) -> Dict[str, int]:
    """Ensure tag rows exist for the provided mapping and return ids.

    Args:
        conn: sqlite3.Connection
        tags: mapping of tag code -> human readable name

    Returns:
        mapping of tag code -> tag id
    """
    cur = conn.cursor()
    code_to_id: Dict[str, int] = {}
    for code, name in tags.items():
        cur.execute(
            "INSERT OR IGNORE INTO tag (code, name) VALUES (?, ?)", (code, name)
        )
    conn.commit()
    for code in tags.keys():
        cur.execute("SELECT id FROM tag WHERE code = ?", (code,))
        row = cur.fetchone()
        if row:
            code_to_id[code] = row[0]
    return code_to_id


def _ensure_tags(conn: sqlite3.Connection, codes: Iterable[str]) -> Dict[str, int]:
    """Ensure tag rows exist for the provided codes and return ids.

    Unlike `_upsert_tags` this accepts an iterable of codes (possibly
    without human-readable names) and inserts placeholder rows when
    necessary.

    Args:
        conn: sqlite3.Connection
        codes: iterable of tag codes

    Returns:
        mapping of tag code -> tag id
    """
    cur = conn.cursor()
    code_to_id: Dict[str, int] = {}
    for code in codes:
        if not code:
            continue
        cur.execute(
            "INSERT OR IGNORE INTO tag (code, name) VALUES (?, ?)", (code, None)
        )
    conn.commit()
    for code in codes:
        if not code:
            continue
        cur.execute("SELECT id FROM tag WHERE code = ?", (code,))
        row = cur.fetchone()
        if row:
            code_to_id[code] = row[0]
    return code_to_id


def store_snapshot(
    conn: sqlite3.Connection,
    date_token: str,
    attempt: int,
    items: List[Dict[str, Any]],
    tags: Dict[str, str],
    source_url: Optional[str] = None,
) -> int:
    """Store a parsed snapshot into the database.

    Inserts a `snapshot` row for the given `date_token` and `attempt` (or
    re-uses an existing one), upserts dishes and tags, and writes the
    per-snapshot entries into `snapshot_entry` including `category` and
    `price_eur`.

    The function runs the per-item writes in a transaction to keep the
    snapshot consistent.

    Args:
        conn: sqlite3.Connection
        date_token: date string used to group snapshots (e.g. YYYYMMDD)
        attempt: numeric attempt id for that date (1 or 2)
        items: list of parsed dish dictionaries
        tags: global tag mapping code -> name extracted from the page
        source_url: optional source URL to record (currently unused)

    Returns:
        snapshot_id (int)
    """

    _upsert_tags(conn, tags)

    cur = conn.cursor()
    # create snapshot row if not exists
    cur.execute(
        "INSERT OR IGNORE INTO snapshot (date, attempt) VALUES (?, ?)",
        (date_token, attempt),
    )
    cur.execute(
        "SELECT id FROM snapshot WHERE date = ? AND attempt = ?", (date_token, attempt)
    )
    snapshot_id = cur.fetchone()[0]
    conn.commit()

    # We'll batch insert entries in a transaction
    try:
        conn.execute("BEGIN")
        for it in items:
            dish_id = _upsert_dish(conn, it)
            # ensure tags and dish_tag mapping
            tags = (
                it.get("zusatzstoffe") or []
            )  # German for "additives", also includes tags
            tag_map = _ensure_tags(conn, tags)
            for code, tag_id in tag_map.items():
                cur.execute(
                    "INSERT OR IGNORE INTO dish_tag (dish_id, tag_id) VALUES (?, ?)",
                    (dish_id, tag_id),
                )
            category = it.get("category")
            price = it.get("price_eur")
            cur.execute(
                "INSERT OR REPLACE INTO snapshot_entry (snapshot_id, dish_id, category, price_eur) VALUES (?, ?, ?, ?)",
                (snapshot_id, dish_id, category, price),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return snapshot_id


def compute_empties(conn: sqlite3.Connection, date_token: str) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    # Find snapshot ids for attempt 1 and 2 for this date
    cur.execute("SELECT id FROM snapshot WHERE date = ? AND attempt = 1", (date_token,))
    row1 = cur.fetchone()
    if not row1:
        return []
    sn1 = row1[0]
    cur.execute("SELECT id FROM snapshot WHERE date = ? AND attempt = 2", (date_token,))
    row2 = cur.fetchone()
    if not row2:
        # nothing to compare against yet
        return []
    sn2 = row2[0]

    # dish ids in sn1 that are not in sn2
    cur.execute(
        """
SELECT d.id, d.name, d.canonical_hash
FROM snapshot_entry s1
JOIN dish d ON d.id = s1.dish_id
WHERE s1.snapshot_id = ?
  AND NOT EXISTS (
    SELECT 1 FROM snapshot_entry s2 WHERE s2.snapshot_id = ? AND s2.dish_id = s1.dish_id
  )
""",
        (sn1, sn2),
    )
    rows = cur.fetchall()
    empties: List[Dict[str, Any]] = []
    dish_ids = []
    for r in rows:
        dish_id, name, ch = r
        empties.append({"dish_id": dish_id, "name": name, "canonical_hash": ch})
        dish_ids.append(dish_id)

    # mark went_empty = 1 on the snapshot_entry rows for attempt=1
    if dish_ids:
        q = f"UPDATE snapshot_entry SET went_empty = 1 WHERE snapshot_id = ? AND dish_id IN ({','.join(['?']*len(dish_ids))})"
        cur.execute(q, (sn1, *dish_ids))

    # update snapshot metadata for attempt=2 with count and timestamp
    import datetime as _dt

    cur.execute(
        "UPDATE snapshot SET empties_count = ?, computed_at = ? WHERE id = ?",
        (len(dish_ids), _dt.datetime.utcnow().isoformat() + "Z", sn2),
    )
    conn.commit()
    return empties
