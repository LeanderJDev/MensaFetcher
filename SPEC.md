# MensaFetcher Specification

## Purpose

This document specifies:

- how MensaFetcher fetches and parses menu data,
- how ingest runs are stored in SQLite,
- which fields are persisted and how they are interpreted.

The specification reflects the current implementation in the repository.

## System Overview

MensaFetcher consists of three logical stages:

1. Fetch HTML from a my-mensa endpoint.
2. Parse dishes and metadata from HTML.
3. Persist a normalized snapshot into SQLite and (on second run) compute "went empty" dishes.

Main modules:

- `src/parser.py`: HTTP fetch + HTML parsing
- `src/ingest.py`: CLI orchestrator for ingest runs
- `src/db.py`: schema initialization and database write logic

## Fetching and Ingest Process

### 1) Ingest CLI invocation

`src/ingest.py` is run with:

- `--url` (required): my-mensa menu URL
- `--db` (optional, default `mensa.db`): SQLite file path
- `--date` (optional): `today`/`now` or ISO date (`YYYY-MM-DD`), default is today
- `--attempt` (required): `1` (first fetch) or `2` (second fetch)

The process is intended for two runs per day:

- attempt 1: baseline morning snapshot
- attempt 2: later snapshot for comparison

### 2) Date handling

The ingest script parses `--date` into a Python `datetime.date`.

That value is used in two ways:

- for parser day selection: converted to a day token `YYYYDDD` (year and day-of-year)
- for DB snapshot date: stored in SQLite `snapshot.date` as text (ISO-like date string)

### 3) HTML fetch

`src/parser.py` performs an HTTP GET with:

- timeout: 10 seconds
- custom `User-Agent`

HTTP errors are raised and abort ingest.

### 4) Parsing

`parse_url_to_items(url, date)` loads HTML and calls `parse_html(html, date_token)`.

The parser:

- extracts global additive/tag mapping from inline JavaScript (`zusatzstoffe[...] = JSON.parse(...)`)
- selects the menu block for the requested day token (`_tag_<number>`), fallback to first available block
- finds dish nodes via `li[data-gid][ref]`
- extracts fields per dish:
    - `name`
    - `description`
    - `category`
    - `zusatzstoffe` (codes from `ref` attribute)
    - `tags` (from `img[data-type]`)
    - `price_eur`

Returned payload:

- `items`: list of dish objects
- `tags`: global map `code -> human-readable name` from JS mapping

### 5) DB initialization

Before writing data, `db.init_db(conn)` ensures all required tables and indexes exist.

### 6) Snapshot persistence

`db.store_snapshot(conn, date_token, attempt, items, tags, source_url)` executes:

1. Upsert global tags (`tag` table) from parser mapping.
2. Create or reuse snapshot row (`snapshot`) with unique key `(date, attempt)`.
3. For each parsed dish item:
    - compute canonical hash based on normalized `name`, `description`, sorted `tags`
    - upsert dish (`dish`) by canonical hash
    - ensure additive codes from `zusatzstoffe` exist in `tag`
    - create many-to-many links in `dish_tag`
    - insert/update per-snapshot row in `snapshot_entry` with category and price

Writes are wrapped in a transaction for consistency.

### 7) Empty-dish computation (attempt 2)

When ingest is run with `--attempt 2`, `db.compute_empties(conn, date_token)`:

1. loads snapshot IDs for the same date with attempts 1 and 2,
2. finds dishes present in attempt 1 but missing in attempt 2,
3. marks those attempt-1 `snapshot_entry` rows as `went_empty = 1`,
4. updates attempt-2 snapshot metadata:
    - `empties_count`
    - `computed_at` (UTC timestamp).

Result is returned as a list of empty dish descriptors.

## Database Specification

Database engine: SQLite

### Table: `dish`

Canonical dish catalog, deduplicated across snapshots.

- `id` INTEGER PRIMARY KEY
- `canonical_hash` TEXT UNIQUE NOT NULL
- `name` TEXT
- `description` TEXT

Notes:

- `canonical_hash` is SHA1 of lowercased `name|description|sorted(tags)`.
- Existing rows are updated if name/description changed.

### Table: `tag`

Tag/additive code dictionary.

- `id` INTEGER PRIMARY KEY
- `code` TEXT UNIQUE NOT NULL
- `name` TEXT

Notes:

- Tags come from parser global mapping and dish-level additive code extraction.
- Some rows can have `name = NULL` (code known, label unknown).

### Table: `dish_tag`

Many-to-many relationship between dishes and tags.

- `dish_id` INTEGER NOT NULL, FK -> `dish(id)`
- `tag_id` INTEGER NOT NULL, FK -> `tag(id)`
- PRIMARY KEY (`dish_id`, `tag_id`)

### Table: `snapshot`

One ingest run for one date and attempt.

- `id` INTEGER PRIMARY KEY
- `date` TEXT NOT NULL
- `attempt` INTEGER NOT NULL
- `created_at` TEXT DEFAULT current UTC timestamp
- `empties_count` INTEGER DEFAULT 0
- `computed_at` TEXT

Constraints:

- UNIQUE INDEX on (`date`, `attempt`)

Semantics:

- `(date, attempt=1)` and `(date, attempt=2)` represent the two daily checks.
- `empties_count` and `computed_at` are set during second-run comparison.

### Table: `snapshot_entry`

Dish occurrence in a specific snapshot.

- `snapshot_id` INTEGER NOT NULL, FK -> `snapshot(id)`
- `dish_id` INTEGER NOT NULL, FK -> `dish(id)`
- `category` TEXT
- `price_eur` REAL
- `went_empty` INTEGER DEFAULT 0
- PRIMARY KEY (`snapshot_id`, `dish_id`)

Semantics:

- A row exists if dish was present in that snapshot.
- `went_empty = 1` means: dish was present in attempt 1 but not in attempt 2 (same date).

## Data Relationships

- One `snapshot` has many `snapshot_entry` rows.
- One `dish` appears in many `snapshot_entry` rows.
- `dish` and `tag` are linked via `dish_tag` (many-to-many).

## Operational Behavior and Error Handling

- Ingest enables SQLite pragmas: foreign keys ON, WAL mode, normal sync, busy timeout.
- Parsing/fetching/DB errors cause non-zero exit (`sys.exit(1)`).
- Optional notification command (`--notify-cmd` or `MENSA_NOTIFY_CMD`) is called with subject/body on ingest failures.

## Known Current Constraints

- `source_url` is accepted in `store_snapshot(...)` but currently not persisted to a DB column.
- Empty-dish comparison only evaluates attempt 1 vs attempt 2 for the same date.
- Category extraction depends on CSS class position in dish nodes and may be fragile if upstream HTML changes.
