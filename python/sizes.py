"""Storage and generation comparison, all loaded server-side so it is fast.

  1. IP addresses: VARCHAR(45) vs INET6 vs INET4 (same data in all three)
  2. Identifiers: CHAR(36) vs UUID type, and (if the server has them) UUID_v4() / UUID_v7()

Run from the repository root:  python python/sizes.py
Quick test run:                python python/sizes.py --rows 20000 --runs 2
"""
import argparse
import statistics
import time

import pymysql

from demo import wait_for_db

# Fixed statements only. Values are passed as parameters, never built into the SQL.
SETUP = (
    "CREATE OR REPLACE TABLE size_ip_text (ip VARCHAR(45) NOT NULL)",
    "CREATE OR REPLACE TABLE size_ip_inet6 (ip INET6 NOT NULL)",
    "CREATE OR REPLACE TABLE size_ip_inet4 (ip INET4 NOT NULL)",
    "CREATE OR REPLACE TABLE size_id_char (id CHAR(36) PRIMARY KEY)",
    "CREATE OR REPLACE TABLE size_id_uuid (id UUID PRIMARY KEY)",
    "CREATE OR REPLACE TABLE size_id_uuid_v4 (id UUID PRIMARY KEY)",
    "CREATE OR REPLACE TABLE size_id_uuid_v7 (id UUID PRIMARY KEY)",
)
CLEANUP = (
    "DROP TABLE IF EXISTS size_ip_text, size_ip_inet6, size_ip_inet4",
    "DROP TABLE IF EXISTS size_id_char, size_id_uuid, size_id_uuid_v4, size_id_uuid_v7",
)
LOAD_IP_TEXT = (
    "INSERT INTO size_ip_text (ip) "
    "SELECT INET_NTOA(FLOOR(RAND() * 4294967296)) FROM seq_1_to_1000000 LIMIT %s"
)
LOAD_IP_INET6 = "INSERT INTO size_ip_inet6 (ip) SELECT CONCAT('::ffff:', ip) FROM size_ip_text"
LOAD_IP_INET4 = "INSERT INTO size_ip_inet4 (ip) SELECT ip FROM size_ip_text"

# (label, table-size key, truncate, load, needs_new_uuid_functions)
ID_VARIANTS = (
    ("CHAR(36), UUID()", "size_id_char", "TRUNCATE TABLE size_id_char",
     "INSERT INTO size_id_char (id) SELECT UUID() FROM seq_1_to_1000000 LIMIT %s", False),
    ("UUID type, UUID()", "size_id_uuid", "TRUNCATE TABLE size_id_uuid",
     "INSERT INTO size_id_uuid (id) SELECT UUID() FROM seq_1_to_1000000 LIMIT %s", False),
    ("UUID type, UUID_v4()", "size_id_uuid_v4", "TRUNCATE TABLE size_id_uuid_v4",
     "INSERT INTO size_id_uuid_v4 (id) SELECT UUID_v4() FROM seq_1_to_1000000 LIMIT %s", True),
    ("UUID type, UUID_v7()", "size_id_uuid_v7", "TRUNCATE TABLE size_id_uuid_v7",
     "INSERT INTO size_id_uuid_v7 (id) SELECT UUID_v7() FROM seq_1_to_1000000 LIMIT %s", True),
)
ANALYZE = (
    "ANALYZE TABLE size_ip_text", "ANALYZE TABLE size_ip_inet6", "ANALYZE TABLE size_ip_inet4",
    "ANALYZE TABLE size_id_char", "ANALYZE TABLE size_id_uuid",
    "ANALYZE TABLE size_id_uuid_v4", "ANALYZE TABLE size_id_uuid_v7",
)
SIZES_QUERY = (
    "SELECT table_name, data_length + index_length FROM information_schema.tables "
    "WHERE table_schema = DATABASE()"
)


def has_new_uuid_functions(cur):
    try:
        cur.execute("SELECT UUID_v4(), UUID_v7()")
        cur.fetchall()
        return True
    except pymysql.err.Error:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=200_000, help="rows per table (max 1,000,000)")
    parser.add_argument("--runs", type=int, default=3, help="measured load runs per id variant")
    args = parser.parse_args()
    if not 1 <= args.rows <= 1_000_000:
        raise SystemExit("--rows must be between 1 and 1,000,000")

    if args.rows < 100_000:
        print("Warning: table sizes from information_schema are estimates and are unreliable for small "
              "tables. Use 100,000+ rows for the size numbers (quick runs are fine for checking it works).")

    conn = wait_for_db()
    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    print("MariaDB version:", cur.fetchone()[0])
    new_uuid = has_new_uuid_functions(cur)
    if not new_uuid:
        print("UUID_v4()/UUID_v7() are not available on this server version: those rows are skipped.")

    try:
        for statement in SETUP:
            cur.execute(statement)

        # 1. IP addresses: the same random addresses in three column types.
        cur.execute(LOAD_IP_TEXT, (args.rows,))
        cur.execute(LOAD_IP_INET6)
        cur.execute(LOAD_IP_INET4)
        conn.commit()

        # 2. Identifiers: timed server-side load, repeated, with a warm-up.
        id_times = {}
        for label, _, truncate, load, needs_new in ID_VARIANTS:
            if needs_new and not new_uuid:
                continue
            times = []
            for run in range(args.runs + 1):
                cur.execute(truncate)
                start = time.perf_counter()
                cur.execute(load, (args.rows,))
                conn.commit()
                if run > 0:
                    times.append(time.perf_counter() - start)
            id_times[label] = times

        for statement in ANALYZE:
            cur.execute(statement)
            cur.fetchall()
        cur.execute(SIZES_QUERY)
        sizes = dict(cur.fetchall())
    finally:
        for statement in CLEANUP:
            cur.execute(statement)
        conn.commit()
        conn.close()

    print(f"\n=== IP address storage, {args.rows} rows (paste into README) ===")
    print("| Column type | Table size (bytes) |")
    print("|---|---|")
    print(f"| VARCHAR(45) | {sizes['size_ip_text']:,} |")
    print(f"| INET6 | {sizes['size_ip_inet6']:,} |")
    print(f"| INET4 | {sizes['size_ip_inet4']:,} |")

    print(f"\n=== Identifiers, {args.rows} rows, {args.runs} measured runs (paste into README) ===")
    print("| Variant | Load time mean ± sd (s) | Table size (bytes) |")
    print("|---|---|---|")
    for label, key, _, _, _ in ID_VARIANTS:
        if label not in id_times:
            continue
        times = id_times[label]
        sd = statistics.stdev(times) if len(times) > 1 else 0.0
        print(f"| {label} | {statistics.mean(times):.2f} ± {sd:.2f} | {sizes[key]:,} |")


if __name__ == "__main__":
    main()
