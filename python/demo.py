"""Demo and benchmark: modern MariaDB features vs. the same job done the old way.

Run from the repository root:  python python/demo.py
Quick test run:                python python/demo.py --rows 2000 --runs 2
"""
import argparse
import ipaddress
import os
import random
import statistics
import time
import uuid

import pymysql
from dotenv import load_dotenv

import results_io

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))

# Every SQL statement in this file is a fixed string. Values are always passed as
# parameters (%s), and no statement is ever built from variables.
RESET_STATEMENTS = (
    "SET FOREIGN_KEY_CHECKS = 0",
    "TRUNCATE TABLE clicks",
    "TRUNCATE TABLE links",
    "TRUNCATE TABLE clicks_legacy",
    "TRUNCATE TABLE links_legacy",
    "SET FOREIGN_KEY_CHECKS = 1",
)
ANALYZE_STATEMENTS = (
    "ANALYZE TABLE links",
    "ANALYZE TABLE links_legacy",
    "ANALYZE TABLE clicks",
    "ANALYZE TABLE clicks_legacy",
)
INSERT_LINK_MODERN = "INSERT INTO links (target_url) VALUES (%s) RETURNING id, created_at"
INSERT_LINK_LEGACY = "INSERT INTO links_legacy (id, target_url) VALUES (%s, %s)"
SELECT_CREATED_LEGACY = "SELECT created_at FROM links_legacy WHERE id = %s"
INSERT_CLICK_MODERN = "INSERT INTO clicks (link_id, client_ip) VALUES (%s, %s)"
INSERT_CLICK_LEGACY = "INSERT INTO clicks_legacy (link_id, client_ip) VALUES (%s, %s)"
SIZES_QUERY = (
    "SELECT table_name, data_length + index_length FROM information_schema.tables "
    "WHERE table_schema = DATABASE() ORDER BY table_name"
)


def connect():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database="shortener",
        autocommit=False,
    )


def wait_for_db(timeout=90):
    """Retry until the server accepts connections AND sql/*.sql has finished loading."""
    deadline = time.time() + timeout
    while True:
        try:
            conn = connect()
            conn.cursor().execute("SELECT 1 FROM app_clicks LIMIT 1")  # created last (sql/03_app.sql)
            return conn
        except pymysql.err.Error as exc:
            if time.time() > deadline:
                raise SystemExit(f"Database not ready after {timeout}s: {exc}")
            time.sleep(2)


def reset(cur):
    for statement in RESET_STATEMENTS:
        cur.execute(statement)


def random_ip():
    return str(ipaddress.IPv4Address(random.getrandbits(32)))


def to_inet6(ip):
    """Write IPv4 in IPv4-mapped form ('::ffff:10.0.0.2') for INET6 columns.
    MariaDB 10.11 rejects a plain '10.0.0.2' there; 13.0.2 accepts it. The mapped
    form works on both."""
    return ip if ":" in ip else "::ffff:" + ip


# ---------- Demo 1: RETURNING ----------
def demo_returning(cur):
    cur.execute(INSERT_LINK_MODERN, ("https://example.com",))
    print("Modern: one statement gave back:", cur.fetchone())

    new_id = str(uuid.uuid4())  # legacy: we must invent the id ourselves...
    cur.execute(INSERT_LINK_LEGACY, (new_id, "https://example.com"))
    cur.execute(SELECT_CREATED_LEGACY, (new_id,))  # ...and ask again to read created_at
    print("Legacy: needed a 2nd query to read created_at:", cur.fetchone())


# ---------- Demo 2: how IPs sort ----------
def demo_ip_sort(cur):
    ips = ["10.0.0.2", "10.0.0.10", "10.0.0.9", "192.168.1.1", "2001:db8::1"]
    cur.execute("SELECT id FROM links LIMIT 1")
    modern_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM links_legacy LIMIT 1")
    legacy_id = cur.fetchone()[0]
    for ip in ips:
        cur.execute(INSERT_CLICK_MODERN, (modern_id, to_inet6(ip)))
        cur.execute(INSERT_CLICK_LEGACY, (legacy_id, ip))
    cur.execute("SELECT client_ip FROM clicks ORDER BY client_ip")
    print("INET6 order  :", [r[0] for r in cur.fetchall()])
    cur.execute("SELECT client_ip FROM clicks_legacy ORDER BY client_ip")
    print("VARCHAR order:", [r[0] for r in cur.fetchall()])


# ---------- Benchmark ----------
def load_modern(cur, rows):
    """1 query per link: RETURNING hands back id and created_at."""
    ids, queries = [], 0
    start = time.perf_counter()
    for i in range(rows):
        cur.execute(INSERT_LINK_MODERN, (f"https://example.com/page/{i}",))
        ids.append(cur.fetchone()[0])
        queries += 1
    return ids, time.perf_counter() - start, queries


def load_legacy(cur, rows):
    """2 queries per link: INSERT, then SELECT to read the server-set created_at."""
    ids, queries = [], 0
    start = time.perf_counter()
    for i in range(rows):
        new_id = str(uuid.uuid4())
        cur.execute(INSERT_LINK_LEGACY, (new_id, f"https://example.com/page/{i}"))
        cur.execute(SELECT_CREATED_LEGACY, (new_id,))
        cur.fetchone()
        ids.append(new_id)
        queries += 2
    return ids, time.perf_counter() - start, queries


def load_clicks(cur, ids, rows, modern):
    data = []
    for _ in range(rows):
        ip = random_ip()
        data.append((random.choice(ids), to_inet6(ip) if modern else ip))
    cur.executemany(INSERT_CLICK_MODERN if modern else INSERT_CLICK_LEGACY, data)


def summarize(times):
    mean = statistics.mean(times)
    sd = statistics.stdev(times) if len(times) > 1 else 0.0
    return mean, sd, min(times), max(times)


def get_sizes(cur):
    for statement in ANALYZE_STATEMENTS:
        cur.execute(statement)
        cur.fetchall()
    cur.execute(SIZES_QUERY)
    return dict(cur.fetchall())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=20_000, help="links (and clicks) per run")
    parser.add_argument("--runs", type=int, default=5, help="measured runs (after 1 warm-up)")
    parser.add_argument("--json", help="also save the results to this JSON file")
    args = parser.parse_args()

    conn = wait_for_db()
    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    print("MariaDB version:", cur.fetchone()[0], "\n")

    reset(cur)
    demo_returning(cur)
    demo_ip_sort(cur)
    conn.commit()

    print(f"\nBenchmark: {args.rows} link inserts, 1 warm-up run + {args.runs} measured runs")
    modern_times, legacy_times = [], []
    modern_q = legacy_q = 0
    for run in range(args.runs + 1):
        reset(cur)
        conn.commit()
        modern_ids, t_modern, modern_q = load_modern(cur, args.rows)
        conn.commit()
        legacy_ids, t_legacy, legacy_q = load_legacy(cur, args.rows)
        conn.commit()
        label = "warm-up (discarded)" if run == 0 else f"run {run}"
        print(f"  {label}: modern {t_modern:.2f}s | legacy {t_legacy:.2f}s")
        if run > 0:
            modern_times.append(t_modern)
            legacy_times.append(t_legacy)

    load_clicks(cur, modern_ids, args.rows, modern=True)
    load_clicks(cur, legacy_ids, args.rows, modern=False)
    conn.commit()
    sizes = get_sizes(cur)

    m_mean, m_sd, m_min, m_max = summarize(modern_times)
    l_mean, l_sd, l_min, l_max = summarize(legacy_times)
    results_io.save(args.json, cur, args, {
        "queries_per_insert": {"modern": modern_q / args.rows, "legacy": legacy_q / args.rows},
        "insert_seconds": {"modern": modern_times, "legacy": legacy_times},
        "table_bytes": {
            "links": sizes["links"], "links_legacy": sizes["links_legacy"],
            "clicks": sizes["clicks"], "clicks_legacy": sizes["clicks_legacy"],
        },
    })
    conn.close()

    print("\n=== Results (paste into README) ===")
    print("| Comparison | Modern | Legacy |")
    print("|---|---|---|")
    print(f"| Queries per link insert | {modern_q / args.rows:.0f} | {legacy_q / args.rows:.0f} |")
    print(f"| Time for {args.rows} inserts, mean ± sd (s) | {m_mean:.2f} ± {m_sd:.2f} | {l_mean:.2f} ± {l_sd:.2f} |")
    print(f"| Time, min–max (s) | {m_min:.2f}–{m_max:.2f} | {l_min:.2f}–{l_max:.2f} |")
    print(f"| links table size (bytes) | {sizes['links']:,} | {sizes['links_legacy']:,} |")
    print(f"| clicks table size (bytes) | {sizes['clicks']:,} | {sizes['clicks_legacy']:,} |")


if __name__ == "__main__":
    main()
