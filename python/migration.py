"""Schema-change timing: ALGORITHM=INSTANT vs ALGORITHM=COPY on a table that already holds rows.

Run from the repository root:  python python/migration.py
Quick test run:                python python/migration.py --rows 50000 --runs 2
"""
import argparse
import statistics
import time

from demo import wait_for_db

# Fixed statements only. Values are passed as parameters, never built into the SQL.
CREATE_TABLE = (
    "CREATE OR REPLACE TABLE migration_test ("
    "id BIGINT AUTO_INCREMENT PRIMARY KEY, "
    "payload VARCHAR(100) NOT NULL, "
    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
)
# seq_1_to_1000000 is MariaDB's built-in SEQUENCE engine: it generates rows on the server.
FILL_TABLE = "INSERT INTO migration_test (payload) SELECT CONCAT('row-', seq) FROM seq_1_to_1000000 LIMIT %s"
DROP_TABLE = "DROP TABLE IF EXISTS migration_test"

# (label, statement), run in this order each round so the table ends each round unchanged.
CHANGES = (
    ("ADD COLUMN, INSTANT", "ALTER TABLE migration_test ADD COLUMN extra INT NULL, ALGORITHM=INSTANT"),
    ("DROP COLUMN, INSTANT", "ALTER TABLE migration_test DROP COLUMN extra, ALGORITHM=INSTANT"),
    ("ADD COLUMN, COPY", "ALTER TABLE migration_test ADD COLUMN extra INT NULL, ALGORITHM=COPY"),
    ("DROP COLUMN, COPY", "ALTER TABLE migration_test DROP COLUMN extra, ALGORITHM=COPY"),
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=500_000, help="rows in the test table (max 1,000,000)")
    parser.add_argument("--runs", type=int, default=3, help="measured rounds (after 1 warm-up)")
    args = parser.parse_args()
    if not 1 <= args.rows <= 1_000_000:
        raise SystemExit("--rows must be between 1 and 1,000,000")

    conn = wait_for_db()
    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    print("MariaDB version:", cur.fetchone()[0])

    results = {label: [] for label, _ in CHANGES}
    try:
        cur.execute(CREATE_TABLE)
        cur.execute(FILL_TABLE, (args.rows,))
        conn.commit()
        print(f"Table migration_test filled with {args.rows} rows. 1 warm-up round + {args.runs} measured rounds.\n")

        for run in range(args.runs + 1):
            line = []
            for label, statement in CHANGES:
                start = time.perf_counter()
                cur.execute(statement)
                elapsed = time.perf_counter() - start
                line.append(f"{label}: {elapsed:.3f}s")
                if run > 0:
                    results[label].append(elapsed)
            print(("warm-up (discarded)" if run == 0 else f"round {run}") + " | " + " | ".join(line))
    finally:
        cur.execute(DROP_TABLE)
        conn.commit()
        conn.close()

    print(f"\n=== Results for {args.rows} rows (paste into README) ===")
    print("| Change | mean ± sd (s) | min–max (s) |")
    print("|---|---|---|")
    for label, times in results.items():
        sd = statistics.stdev(times) if len(times) > 1 else 0.0
        print(f"| {label} | {statistics.mean(times):.3f} ± {sd:.3f} | {min(times):.3f}–{max(times):.3f} |")


if __name__ == "__main__":
    main()
