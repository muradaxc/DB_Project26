"""Schema changes on a table that already holds rows.

1. ALGORITHM=INSTANT vs ALGORITHM=COPY for ADD, DROP and MODIFY (widen) COLUMN.
2. Progress reporting: while a COPY rebuild runs on one connection, a second connection reads
   its live progress from information_schema.PROCESSLIST (columns STAGE, MAX_STAGE, PROGRESS).

Run from the repository root:  python python/migration.py
Quick test run:                python python/migration.py --rows 50000 --runs 2
"""
import argparse
import statistics
import threading
import time

import results_io
from demo import connect, wait_for_db

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
RESTORE_WIDTH = "ALTER TABLE migration_test MODIFY payload VARCHAR(100) NOT NULL"

# (label, timed statement, untimed statement that puts the table back, or None)
CHANGES = (
    ("ADD COLUMN, INSTANT", "ALTER TABLE migration_test ADD COLUMN extra INT NULL, ALGORITHM=INSTANT", None),
    ("DROP COLUMN, INSTANT", "ALTER TABLE migration_test DROP COLUMN extra, ALGORITHM=INSTANT", None),
    ("MODIFY COLUMN (widen), INSTANT",
     "ALTER TABLE migration_test MODIFY payload VARCHAR(200) NOT NULL, ALGORITHM=INSTANT", RESTORE_WIDTH),
    ("ADD COLUMN, COPY", "ALTER TABLE migration_test ADD COLUMN extra INT NULL, ALGORITHM=COPY", None),
    ("DROP COLUMN, COPY", "ALTER TABLE migration_test DROP COLUMN extra, ALGORITHM=COPY", None),
    ("MODIFY COLUMN (widen), COPY",
     "ALTER TABLE migration_test MODIFY payload VARCHAR(200) NOT NULL, ALGORITHM=COPY", RESTORE_WIDTH),
)

PROGRESS_ALTER = "ALTER TABLE migration_test FORCE, ALGORITHM=COPY"
PROGRESS_QUERY = (
    "SELECT STAGE, MAX_STAGE, PROGRESS FROM information_schema.PROCESSLIST WHERE ID = %s"
)


def watch_progress(rows):
    """Run a COPY rebuild on one connection and sample its progress from another."""
    worker, watcher = connect(), connect()
    worker_id = worker.thread_id()
    samples, done = [], threading.Event()

    def rebuild():
        try:
            worker.cursor().execute(PROGRESS_ALTER)
        finally:
            done.set()

    start = time.perf_counter()
    thread = threading.Thread(target=rebuild)
    thread.start()
    wcur = watcher.cursor()
    while not done.is_set():
        wcur.execute(PROGRESS_QUERY, (worker_id,))
        row = wcur.fetchone()
        if row and row[2] is not None and float(row[2]) > 0:
            samples.append({
                "t": round(time.perf_counter() - start, 3),
                "stage": int(row[0]), "max_stage": int(row[1]), "progress_pct": float(row[2]),
            })
        watcher.commit()  # new snapshot for the next read
        time.sleep(0.01)
    thread.join()
    total = time.perf_counter() - start
    worker.close()
    watcher.close()
    return {"rows": rows, "rebuild_seconds": total, "samples": samples}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=500_000, help="rows in the test table (max 1,000,000)")
    parser.add_argument("--runs", type=int, default=3, help="measured rounds (after 1 warm-up)")
    parser.add_argument("--json", help="also save the results to this JSON file")
    args = parser.parse_args()
    if not 1 <= args.rows <= 1_000_000:
        raise SystemExit("--rows must be between 1 and 1,000,000")

    conn = wait_for_db()
    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    print("MariaDB version:", cur.fetchone()[0])

    results = {label: [] for label, _, _ in CHANGES}
    try:
        cur.execute(CREATE_TABLE)
        cur.execute(FILL_TABLE, (args.rows,))
        conn.commit()
        print(f"Table migration_test filled with {args.rows} rows. 1 warm-up round + {args.runs} measured rounds.\n")

        for run in range(args.runs + 1):
            line = []
            for label, statement, restore in CHANGES:
                start = time.perf_counter()
                cur.execute(statement)
                elapsed = time.perf_counter() - start
                if restore:
                    cur.execute(restore)
                line.append(f"{label}: {elapsed:.3f}s")
                if run > 0:
                    results[label].append(elapsed)
            print(("warm-up (discarded)" if run == 0 else f"round {run}") + " | " + " | ".join(line))

        print("\nProgress reporting: rebuilding the table (ALGORITHM=COPY) while a 2nd connection watches it")
        progress = watch_progress(args.rows)
        for s in progress["samples"][:: max(1, len(progress["samples"]) // 10)]:
            print(f"  t={s['t']:.2f}s  stage {s['stage']}/{s['max_stage']}  {s['progress_pct']:.1f}%")
        print(f"  {len(progress['samples'])} progress readings during a {progress['rebuild_seconds']:.2f}s rebuild")

        results_io.save(args.json, cur, args, {"alter_seconds": results, "progress": progress})
    finally:
        cur.execute(DROP_TABLE)
        conn.commit()
        conn.close()

    print(f"\n=== Results for {args.rows} rows ===")
    print("| Change | mean ± sd (s) | min–max (s) |")
    print("|---|---|---|")
    for label, times in results.items():
        sd = statistics.stdev(times) if len(times) > 1 else 0.0
        print(f"| {label} | {statistics.mean(times):.3f} ± {sd:.3f} | {min(times):.3f}–{max(times):.3f} |")


if __name__ == "__main__":
    main()
