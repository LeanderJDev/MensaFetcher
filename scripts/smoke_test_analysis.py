"""Smoke test for analysis helpers.

Runs a few checks against the provided SQLite DB:
- lists snapshots
- exports the first snapshot to CSV
- creates two PNGs: price histogram and empties time series

Usage:
    python3 scripts/smoke_test_analysis.py --db data/mensa_260511.db --out tmp/smoke_outputs

Exit code: 0 on success, non‑zero on failures.
"""

from __future__ import annotations

import argparse
import os
import sys

# Add project root to path so we can import from scripts/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

import matplotlib.pyplot as plt
import pandas as pd

from scripts.analysis_utils import open_conn, list_snapshots, export_snapshot_to_pandas


def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)


def plot_price_hist(df: pd.DataFrame, out_path: str) -> None:
    prices = df["price_eur"].dropna().astype(float)
    if prices.empty:
        print("No prices available to plot.")
        return
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].hist(prices, bins=20)
    axes[0].set_title("Preisverteilung")
    axes[0].set_xlabel("EUR")
    axes[1].boxplot(prices, vert=False)
    axes[1].set_title("Boxplot Preise")
    plt.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def plot_empties_time_series(conn, out_path: str) -> None:
    q = "SELECT date, empties_count FROM snapshot ORDER BY date"
    rows = conn.execute(q).fetchall()
    if not rows:
        print("No snapshot rows found for empties time series.")
        return
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    if df.empty:
        print("No valid dates for empties time series.")
        return
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(df["date"], df["empties_count"].fillna(0).astype(int), marker="o")
    ax.set_title("Empties Count über Zeit")
    ax.set_xlabel("Datum")
    ax.set_ylabel("empties_count")
    fig.autofmt_xdate()
    fig.savefig(out_path)
    plt.close(fig)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/mensa_260511.db", help="Path to sqlite DB")
    p.add_argument("--out", default="tmp/smoke_outputs", help="Output directory")
    args = p.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"Database file not found: {args.db}")
        return 2

    ensure_dir(args.out)
    conn = open_conn(args.db)

    snaps = list_snapshots(conn)
    print("Found snapshots:", len(snaps))
    if not snaps:
        print("No snapshots found — nothing to export.")
        return 3

    first_id = snaps[0]["id"]
    df = export_snapshot_to_pandas(conn, first_id)
    csv_path = os.path.join(args.out, f"snapshot_{first_id}.csv")
    df.to_csv(csv_path, index=False)
    print("Exported snapshot to", csv_path)

    # Price plot
    price_png = os.path.join(args.out, f"prices_snapshot_{first_id}.png")
    plot_price_hist(df, price_png)
    print("Wrote price plot to", price_png)

    # Empties time series
    empties_png = os.path.join(args.out, "empties_timeseries.png")
    plot_empties_time_series(conn, empties_png)
    print("Wrote empties time series to", empties_png)

    return 0


if __name__ == "__main__":
    try:
        rc = main(sys.argv[1:])
    except Exception as e:
        print("Smoke test failed with exception:", e)
        rc = 1
    sys.exit(rc)
