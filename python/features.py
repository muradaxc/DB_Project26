"""The other "old way" costs from the hackathon page, measured.

1. Validation in application code vs. a CHECK (... IS JSON) constraint in the database.
2. A re-runnable schema with DROP TABLE IF EXISTS + CREATE vs. CREATE OR REPLACE, while another
   connection keeps reading the table.
3. UPDATE / DELETE reading from a CTE (MariaDB 12.3+) vs. doing it in the application vs. a
   plain subquery.
4. Global temporary tables (MariaDB 12.3+) vs. CREATE TEMPORARY TABLE in every session.

Features the server does not support are reported as "unsupported" instead of failing, so the
script also runs on older versions.

Run from the repository root:  python python/features.py
Quick test run:                python python/features.py --rows 2000 --runs 2
"""
import argparse
import json
import statistics
import threading
import time

import pymysql

import results_io
from demo import connect, wait_for_db

# ---------- 1. JSON validation ----------
JSON_TABLE_APP = "CREATE OR REPLACE TABLE feat_meta_app (id INT AUTO_INCREMENT PRIMARY KEY, meta TEXT NOT NULL)"
JSON_TABLE_IS_JSON = (
    "CREATE OR REPLACE TABLE feat_meta_db (id INT AUTO_INCREMENT PRIMARY KEY, meta TEXT NOT NULL, "
    "CONSTRAINT meta_is_json CHECK (meta IS JSON))"
)
JSON_TABLE_JSON_VALID = (  # fallback for servers without IS JSON
    "CREATE OR REPLACE TABLE feat_meta_db (id INT AUTO_INCREMENT PRIMARY KEY, meta TEXT NOT NULL, "
    "CONSTRAINT meta_is_json CHECK (JSON_VALID(meta)))"
)
INSERT_META_APP = "INSERT INTO feat_meta_app (meta) VALUES (%s)"
INSERT_META_DB = "INSERT INTO feat_meta_db (meta) VALUES (%s)"
COUNT_BAD_APP = "SELECT COUNT(*) FROM feat_meta_app WHERE NOT JSON_VALID(meta)"
COUNT_BAD_DB = "SELECT COUNT(*) FROM feat_meta_db WHERE NOT JSON_VALID(meta)"
DROP_META = "DROP TABLE IF EXISTS feat_meta_app, feat_meta_db"

# ---------- 2. Re-runnable schema ----------
RERUN_DROP = "DROP TABLE IF EXISTS feat_rerun"
RERUN_CREATE = "CREATE TABLE feat_rerun (id INT PRIMARY KEY, note VARCHAR(20))"
RERUN_REPLACE = "CREATE OR REPLACE TABLE feat_rerun (id INT PRIMARY KEY, note VARCHAR(20))"
RERUN_READ = "SELECT COUNT(*) FROM feat_rerun"

# ---------- 3. UPDATE / DELETE with a CTE ----------
CTE_SETUP = (
    "CREATE OR REPLACE TABLE feat_links (id INT PRIMARY KEY, click_count INT NOT NULL DEFAULT 0)",
    "CREATE OR REPLACE TABLE feat_clicks (id INT AUTO_INCREMENT PRIMARY KEY, link_id INT NOT NULL, KEY (link_id))",
)
CTE_FILL_LINKS = "INSERT INTO feat_links (id) SELECT seq FROM seq_1_to_1000000 LIMIT %s"
# every second link gets three clicks, the rest get none (they are "stale")
CTE_FILL_CLICKS = (
    "INSERT INTO feat_clicks (link_id) SELECT l.seq FROM seq_1_to_1000000 l "
    "JOIN seq_1_to_3 r WHERE l.seq <= %s AND l.seq %% 2 = 0"
)
CTE_RESET_COUNTS = "UPDATE feat_links SET click_count = 0"
CTE_DROP = "DROP TABLE IF EXISTS feat_links, feat_clicks"
CTE_CHECK = "SELECT SUM(click_count), COUNT(*) FROM feat_links"

UPDATE_CTE = (
    "WITH counts AS (SELECT link_id, COUNT(*) AS n FROM feat_clicks GROUP BY link_id) "
    "UPDATE feat_links JOIN counts ON counts.link_id = feat_links.id SET feat_links.click_count = counts.n"
)
UPDATE_CTE_SIMPLE = (  # single-table form, in case the server rejects a CTE joined into UPDATE
    "WITH counts AS (SELECT link_id, COUNT(*) AS n FROM feat_clicks GROUP BY link_id) "
    "UPDATE feat_links SET click_count = (SELECT n FROM counts WHERE counts.link_id = feat_links.id) "
    "WHERE id IN (SELECT link_id FROM counts)"
)
UPDATE_SUBQUERY = (
    "UPDATE feat_links JOIN (SELECT link_id, COUNT(*) AS n FROM feat_clicks GROUP BY link_id) AS counts "
    "ON counts.link_id = feat_links.id SET feat_links.click_count = counts.n"
)
SELECT_COUNTS_APP = "SELECT link_id, COUNT(*) FROM feat_clicks GROUP BY link_id"
UPDATE_ONE_APP = "UPDATE feat_links SET click_count = %s WHERE id = %s"

DELETE_CTE = (
    "WITH stale AS (SELECT l.id FROM feat_links l LEFT JOIN feat_clicks c ON c.link_id = l.id "
    "WHERE c.link_id IS NULL) "
    "DELETE FROM feat_links WHERE id IN (SELECT id FROM stale)"
)
DELETE_SUBQUERY = (
    "DELETE FROM feat_links WHERE id IN (SELECT id FROM (SELECT l.id FROM feat_links l "
    "LEFT JOIN feat_clicks c ON c.link_id = l.id WHERE c.link_id IS NULL) AS stale)"
)
SELECT_STALE_APP = (
    "SELECT l.id FROM feat_links l LEFT JOIN feat_clicks c ON c.link_id = l.id WHERE c.link_id IS NULL"
)
DELETE_ONE_APP = "DELETE FROM feat_links WHERE id = %s"

# ---------- 4. Global temporary tables ----------
GTT_CREATE = (
    "CREATE GLOBAL TEMPORARY TABLE feat_gtt_batch (ip VARCHAR(45) NOT NULL) ON COMMIT PRESERVE ROWS"
)
GTT_DROP = "DROP TABLE IF EXISTS feat_gtt_batch"
GTT_INSERT = "INSERT INTO feat_gtt_batch (ip) VALUES (%s)"
GTT_COUNT = "SELECT COUNT(*) FROM feat_gtt_batch"
TMP_CREATE = "CREATE TEMPORARY TABLE feat_tmp_batch (ip VARCHAR(45) NOT NULL)"
TMP_INSERT = "INSERT INTO feat_tmp_batch (ip) VALUES (%s)"
TMP_COUNT = "SELECT COUNT(*) FROM feat_tmp_batch"


def stats(times):
    return {"mean": statistics.mean(times), "sd": statistics.stdev(times) if len(times) > 1 else 0.0,
            "min": min(times), "max": max(times), "runs": times}


ERRORS = {}  # why a feature was reported as unsupported, saved with the results


def supported(cur, statement, name="feature"):
    try:
        cur.execute(statement)
        return True
    except pymysql.err.Error as exc:  # e.g. a syntax error: the server does not know this feature
        ERRORS[name] = f"{exc.args[0]}: {exc.args[1] if len(exc.args) > 1 else exc}"
        return False


# ---------- 1 ----------
def json_validation(conn, rows):
    cur = conn.cursor()
    cur.execute(JSON_TABLE_APP)
    uses_is_json = supported(cur, JSON_TABLE_IS_JSON, "IS JSON")
    if not uses_is_json:
        cur.execute(JSON_TABLE_JSON_VALID)
    good = [json.dumps({"browser": "firefox", "mobile": i % 2 == 0, "n": i}) for i in range(rows)]
    bad = ["{broken json", "not json", '{"a": }', "", "{'single': 'quotes'}"] * 20  # 100 bad docs

    # The application validates before inserting (legacy) ...
    start = time.perf_counter()
    for doc in good:
        json.loads(doc)
        cur.execute(INSERT_META_APP, (doc,))
    conn.commit()
    t_app = time.perf_counter() - start
    # ... the database validates (modern).
    start = time.perf_counter()
    for doc in good:
        cur.execute(INSERT_META_DB, (doc,))
    conn.commit()
    t_db = time.perf_counter() - start

    # A second client that does not go through the application (an import script, a manual fix).
    rejected_db = 0
    for doc in bad:
        cur.execute(INSERT_META_APP, (doc,))
        try:
            cur.execute(INSERT_META_DB, (doc,))
        except pymysql.err.Error:
            rejected_db += 1
    conn.commit()
    cur.execute(COUNT_BAD_APP)
    bad_app = cur.fetchone()[0]
    cur.execute(COUNT_BAD_DB)
    bad_db = cur.fetchone()[0]
    cur.execute(DROP_META)
    conn.commit()
    return {
        "constraint": "IS JSON" if uses_is_json else "JSON_VALID (IS JSON unsupported)",
        "rows": rows, "insert_seconds": {"app_validation": t_app, "db_check": t_db},
        "bad_docs_from_second_client": len(bad),
        "bad_docs_stored": {"app_validation": bad_app, "db_check": bad_db},
        "rejected_by_db": rejected_db,
    }


# ---------- 2 ----------
def rerun_schema(reruns):
    out = {}
    for mode in ("DROP IF EXISTS + CREATE", "CREATE OR REPLACE"):
        writer = connect()
        writer.autocommit(True)
        wcur = writer.cursor()
        wcur.execute(RERUN_REPLACE)
        stop, errors, reads = threading.Event(), {}, [0]

        def reader():
            r = connect()
            r.autocommit(True)
            rcur = r.cursor()
            while not stop.is_set():
                try:
                    rcur.execute(RERUN_READ)
                    rcur.fetchall()
                    reads[0] += 1
                except pymysql.err.Error as exc:
                    errors[exc.args[0]] = errors.get(exc.args[0], 0) + 1
            r.close()

        thread = threading.Thread(target=reader)
        thread.start()
        start = time.perf_counter()
        for _ in range(reruns):
            if mode == "CREATE OR REPLACE":
                wcur.execute(RERUN_REPLACE)
            else:
                wcur.execute(RERUN_DROP)
                wcur.execute(RERUN_CREATE)
        elapsed = time.perf_counter() - start
        stop.set()
        thread.join()
        wcur.execute(RERUN_DROP)
        writer.close()
        out[mode] = {
            "statements_per_rerun": 1 if mode == "CREATE OR REPLACE" else 2,
            "seconds": elapsed, "reader_ok": reads[0],
            "reader_errors": sum(errors.values()), "error_codes": errors,
        }
        out["reruns"] = reruns
    return out


# ---------- 3 ----------
def cte_dml(conn, rows, runs):
    cur = conn.cursor()
    for statement in CTE_SETUP:
        cur.execute(statement)
    has_cte = supported(cur, "WITH x AS (SELECT 1 AS id) DELETE FROM feat_links WHERE id IN (SELECT id FROM x)",
                        "CTE in DELETE")
    conn.commit()

    def fill():
        cur.execute("TRUNCATE TABLE feat_links")
        cur.execute("TRUNCATE TABLE feat_clicks")
        cur.execute(CTE_FILL_LINKS, (rows,))
        cur.execute(CTE_FILL_CLICKS, (rows,))
        conn.commit()

    def app_update():
        cur.execute(SELECT_COUNTS_APP)
        pairs = [(n, link_id) for link_id, n in cur.fetchall()]
        cur.executemany(UPDATE_ONE_APP, pairs)
        return 1 + len(pairs)  # statements sent

    def app_delete():
        cur.execute(SELECT_STALE_APP)
        ids = [(r[0],) for r in cur.fetchall()]
        cur.executemany(DELETE_ONE_APP, ids)
        return 1 + len(ids)

    variants = {
        "UPDATE": {"in the application": app_update, "subquery (older versions)": (UPDATE_SUBQUERY,),
                   "CTE (12.3+)": (UPDATE_CTE, UPDATE_CTE_SIMPLE)},
        "DELETE": {"in the application": app_delete, "subquery (older versions)": (DELETE_SUBQUERY,),
                   "CTE (12.3+)": (DELETE_CTE,)},
    }
    out = {"cte_supported": has_cte, "links": rows, "stale_links": rows - rows // 2}
    fill()
    for kind, ways in variants.items():
        out[kind] = {}
        for label, way in ways.items():
            if label.startswith("CTE") and not has_cte:
                out[kind][label] = "unsupported"
                continue
            if not callable(way):  # pick the first form this server accepts
                for form in way:
                    cur.execute(CTE_RESET_COUNTS) if kind == "UPDATE" else fill()
                    if supported(cur, form, f"{kind} {label}"):
                        conn.rollback()
                        way = form
                        break
                else:
                    out[kind][label] = "unsupported"
                    continue
            times, statements, check = [], 1, None
            for run in range(runs + 1):
                fill() if kind == "DELETE" else cur.execute(CTE_RESET_COUNTS)
                conn.commit()
                start = time.perf_counter()
                if callable(way):
                    statements = way()
                else:
                    cur.execute(way)
                conn.commit()
                if run > 0:
                    times.append(time.perf_counter() - start)
                cur.execute(CTE_CHECK)
                check = [int(v or 0) for v in cur.fetchone()]
            out[kind][label] = {"statements": statements, "result_check": check, **stats(times)}
            if not callable(way):
                out[kind][label]["sql"] = way
    cur.execute(CTE_DROP)
    conn.commit()
    return out


# ---------- 4 ----------
def global_temporary(sessions, rows_per_session):
    admin = connect()
    acur = admin.cursor()
    acur.execute(GTT_DROP)
    has_gtt = supported(acur, GTT_CREATE, "GLOBAL TEMPORARY TABLE")
    admin.commit()
    ips = [f"10.0.{i // 256}.{i % 256}" for i in range(rows_per_session)]
    out = {"gtt_supported": has_gtt, "sessions": sessions, "rows_per_session": rows_per_session}

    def run(label, setup, insert, count):
        start = time.perf_counter()
        seen = []
        for _ in range(sessions):
            conn = connect()
            cur = conn.cursor()
            for statement in setup:
                cur.execute(statement)
            cur.executemany(insert, [(ip,) for ip in ips])
            conn.commit()
            cur.execute(count)
            seen.append(cur.fetchone()[0])
            conn.close()
        out[label] = {
            "ddl_statements_per_session": len(setup), "seconds": time.perf_counter() - start,
            "each_session_saw_only_its_own_rows": all(n == rows_per_session for n in seen),
        }

    run("CREATE TEMPORARY TABLE per session", (TMP_CREATE,), TMP_INSERT, TMP_COUNT)
    if has_gtt:
        run("GLOBAL TEMPORARY TABLE (12.3+)", (), GTT_INSERT, GTT_COUNT)
        acur.execute(GTT_DROP)
    else:
        out["GLOBAL TEMPORARY TABLE (12.3+)"] = "unsupported"
    admin.commit()
    admin.close()
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=20_000, help="rows for the JSON and CTE tests")
    parser.add_argument("--runs", type=int, default=3, help="measured runs (after 1 warm-up)")
    parser.add_argument("--reruns", type=int, default=200, help="schema re-runs while a reader is busy")
    parser.add_argument("--sessions", type=int, default=100, help="sessions for the temporary-table test")
    parser.add_argument("--json", help="also save the results to this JSON file")
    args = parser.parse_args()

    conn = wait_for_db()
    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    print("MariaDB version:", cur.fetchone()[0])

    print("\n1. Validation: application code vs. CHECK constraint")
    js = json_validation(conn, args.rows)
    print(f"   constraint used: {js['constraint']}")
    print(f"   {js['rows']} good inserts: app {js['insert_seconds']['app_validation']:.2f}s | "
          f"db {js['insert_seconds']['db_check']:.2f}s")
    print(f"   {js['bad_docs_from_second_client']} bad documents from a 2nd client: stored with app validation "
          f"{js['bad_docs_stored']['app_validation']}, stored with CHECK {js['bad_docs_stored']['db_check']}")

    print(f"\n2. Re-running the schema {args.reruns} times while another connection reads the table")
    rr = rerun_schema(args.reruns)
    for mode in ("DROP IF EXISTS + CREATE", "CREATE OR REPLACE"):
        r = rr[mode]
        print(f"   {mode}: {r['seconds']:.2f}s, reader: {r['reader_ok']} ok reads, "
              f"{r['reader_errors']} errors {r['error_codes'] or ''}")

    print(f"\n3. UPDATE / DELETE driven by another query ({args.rows} links, half without clicks)")
    cte = cte_dml(conn, args.rows, args.runs)
    if not cte["cte_supported"]:
        print("   CTEs in UPDATE/DELETE are not supported on this server version (needs 12.3+)")
    for kind in ("UPDATE", "DELETE"):
        for label, r in cte[kind].items():
            if r == "unsupported":
                continue
            print(f"   {kind} {label}: {r['statements']} statement(s), {r['mean']:.3f} ± {r['sd']:.3f}s")

    print(f"\n4. Per-session scratch table, {args.sessions} sessions")
    gtt = global_temporary(args.sessions, 50)
    for label in ("CREATE TEMPORARY TABLE per session", "GLOBAL TEMPORARY TABLE (12.3+)"):
        r = gtt[label]
        if r == "unsupported":
            print(f"   {label}: not supported on this server version ({ERRORS.get('GLOBAL TEMPORARY TABLE')})")
            continue
        print(f"   {label}: {r['ddl_statements_per_session']} DDL per session, {r['seconds']:.2f}s, "
              f"isolated: {r['each_session_saw_only_its_own_rows']}")

    results_io.save(args.json, cur, args, {
        "json_validation": js, "rerun_schema": rr, "cte_dml": cte, "global_temporary": gtt,
        "unsupported_because": ERRORS,
    })
    conn.close()


if __name__ == "__main__":
    main()
