"""
verify_sql.py
-------------
Loads a dataset into an in-memory SQLite database, then runs every query in the sql/
folder against it and prints the results.

Why: I do not want to find out that a query is broken after I have already built the
Power BI report on top of it. This runs the whole SQL layer end to end in about two
seconds, so I run it every time I change a query or regenerate the data.

    python verify_sql.py                # synthetic dataset  (data/)
    python verify_sql.py --real         # real UCI dataset   (data_real/)

SQLite is not the production target (PostgreSQL is), but it needs no install and it
supports the CTEs and window functions these queries rely on. The only thing it cannot
do is PostgreSQL's date subtraction, so this script rewrites those few expressions to
julianday() before executing - the rewrites are listed in DIALECT_FIXES below.
"""

import argparse
import csv
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SQL_DIR = os.path.join(HERE, "..", "sql")

TABLES = [
    "dim_date", "dim_customers", "dim_categories", "dim_products",
    "dim_stores", "fact_orders", "fact_order_items",
]

# PostgreSQL date arithmetic -> SQLite equivalent.
DIALECT_FIXES = [
    (r"\(SELECT max_date FROM ref\)\s*-\s*(\w+)\.last_order_date",
     r"CAST(julianday((SELECT max_date FROM ref)) - julianday(\1.last_order_date) AS INTEGER)"),
    (r"ORDER BY \(SELECT max_date FROM ref\)\s*-\s*cb\.last_order_date ASC",
     r"ORDER BY CAST(julianday((SELECT max_date FROM ref)) - julianday(cb.last_order_date) AS INTEGER) ASC"),
    (r"\border_date\s*-\s*prev_order_date\b",
     r"CAST(julianday(order_date) - julianday(prev_order_date) AS INTEGER)"),
]


def load_csvs(conn, data_dir):
    with open(os.path.join(SQL_DIR, "01_schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())

    for table in TABLES:
        path = os.path.join(data_dir, f"{table}.csv")
        if not os.path.exists(path):
            sys.exit(f"ERROR: missing {path}\nRun the generator (or the cleaner) first.")
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            cols = next(reader)
            rows = list(reader)
        placeholders = ",".join("?" * len(cols))
        conn.executemany(
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", rows)
        print(f"  loaded {table:<18} {len(rows):>8,} rows")
    conn.commit()


def split_statements(sql_text):
    """Strip comments and psql meta-commands, then split on semicolons."""
    out = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or stripped.startswith("\\"):
            continue
        out.append(line)
    joined = "\n".join(out)
    return [s.strip() for s in joined.split(";") if s.strip()]


def run_file(conn, filename, max_rows=8):
    path = os.path.join(SQL_DIR, filename)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for pattern, repl in DIALECT_FIXES:
        text = re.sub(pattern, repl, text)

    print("\n" + "#" * 78)
    print(f"# {filename}")
    print("#" * 78)

    for i, stmt in enumerate(split_statements(text), start=1):
        try:
            cur = conn.execute(stmt)
        except sqlite3.Error as exc:
            print(f"\n  [Q{i}] FAILED: {exc}")
            print("  " + stmt[:300].replace("\n", "\n  "))
            raise SystemExit(1)
        if cur.description is None:
            continue
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print(f"\n  [Q{i}]  {len(rows):,} row(s)")
        if not rows:
            print("        (empty - which is what a data-quality check should return)")
            continue
        widths = [max(len(str(c)), *(len(str(r[j])) for r in rows[:max_rows]))
                  for j, c in enumerate(cols)]
        widths = [min(w, 26) for w in widths]
        header = "  " + " | ".join(str(c)[:26].ljust(w) for c, w in zip(cols, widths))
        print(header)
        print("  " + "-" * (len(header) - 2))
        for r in rows[:max_rows]:
            print("  " + " | ".join(str(v)[:26].ljust(w) for v, w in zip(r, widths)))
        if len(rows) > max_rows:
            print(f"        ... {len(rows) - max_rows:,} more row(s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true",
                    help="use data_real/ (cleaned UCI data) instead of data/")
    ap.add_argument("--files", nargs="*", help="only run these sql files")
    args = ap.parse_args()

    data_dir = os.path.join(HERE, "..", "data_real" if args.real else "data")
    label = "REAL (UCI Online Retail II)" if args.real else "SYNTHETIC"

    print("=" * 78)
    print(f" Verifying the SQL layer against the {label} dataset")
    print("=" * 78)

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    load_csvs(conn, data_dir)

    files = args.files or [
        "03_data_quality_checks.sql",
        "04_revenue_analysis.sql",
        "05_cohort_retention.sql",
        "06_rfm_segmentation.sql",
        "07_pareto_top_customers.sql",
    ]
    for filename in files:
        run_file(conn, filename)

    print("\n" + "=" * 78)
    print(" All queries executed without error.")
    print("=" * 78)


if __name__ == "__main__":
    main()
