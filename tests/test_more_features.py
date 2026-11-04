"""Tests for the claims made by python/features.py, python/migration.py and examples 09-12.

Features that need MariaDB 12.3+ are skipped on older servers; on the version this project pins
(13.0.2, also used in CI) they run.
"""
import re

import pymysql
import pytest

import demo
import features
import migration


def server_version(conn):
    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    return tuple(int(x) for x in re.match(r"(\d+)\.(\d+)", cur.fetchone()[0]).groups())


def test_row_type_procedure_reads_a_whole_row(conn):
    cur = conn.cursor()
    cur.execute("CREATE OR REPLACE TABLE t_row (id INT PRIMARY KEY, url VARCHAR(50), clicks INT)")
    cur.execute("INSERT INTO t_row VALUES (1, 'https://example.com', 4)")
    cur.execute(
        "CREATE OR REPLACE PROCEDURE p_row(IN p_id INT) BEGIN "
        "DECLARE r ROW TYPE OF t_row; "
        "SELECT * INTO r FROM t_row WHERE id = p_id; "
        "SELECT r.url, r.clicks; END"
    )
    cur.execute("CALL p_row(1)")
    assert cur.fetchone() == ("https://example.com", 4)
    cur.nextset()
    cur.execute("DROP PROCEDURE p_row")
    cur.execute("DROP TABLE t_row")
    conn.commit()


def test_check_constraint_rejects_bad_json_that_app_validation_would_let_in(conn):
    result = features.json_validation(conn, rows=50)
    assert result["bad_docs_stored"]["app_validation"] == result["bad_docs_from_second_client"]
    assert result["bad_docs_stored"]["db_check"] == 0


def test_is_json_constraint_exists_on_12_3_and_newer(conn):
    if server_version(conn) < (12, 3):
        pytest.skip("IS JSON needs a newer server")
    result = features.json_validation(conn, rows=10)
    assert result["constraint"] == "IS JSON"


def test_create_or_replace_never_hides_the_table_from_a_reader():
    result = features.rerun_schema(reruns=60)
    assert result["CREATE OR REPLACE"]["reader_errors"] == 0
    assert result["CREATE OR REPLACE"]["reader_ok"] > 0


def test_update_and_delete_give_the_same_result_every_way(conn):
    result = features.cte_dml(conn, rows=200, runs=1)
    for kind in ("UPDATE", "DELETE"):
        checks = {label: r["result_check"] for label, r in result[kind].items() if r != "unsupported"}
        assert len(set(map(tuple, checks.values()))) == 1, checks
    if server_version(conn) >= (12, 3):
        assert result["cte_supported"]
        assert result["UPDATE"]["CTE (12.3+)"] != "unsupported"
        assert result["DELETE"]["CTE (12.3+)"]["statements"] == 1


def test_temporary_tables_are_isolated_per_session():
    result = features.global_temporary(sessions=3, rows_per_session=5)
    for label in ("CREATE TEMPORARY TABLE per session", "GLOBAL TEMPORARY TABLE (12.3+)"):
        r = result[label]
        if r != "unsupported":
            assert r["each_session_saw_only_its_own_rows"]


def test_progress_is_reported_during_a_copy_rebuild(conn):
    cur = conn.cursor()
    cur.execute(migration.CREATE_TABLE)
    cur.execute(migration.FILL_TABLE, (300_000,))
    conn.commit()
    try:
        progress = migration.watch_progress(300_000)
    finally:
        cur.execute(migration.DROP_TABLE)
        conn.commit()
    assert progress["samples"], "no progress readings were seen"
    assert all(0 < s["progress_pct"] <= 100 for s in progress["samples"])


def test_shortener_app_round_trip(conn):
    import app  # noqa: E402  (python/ is on the path via conftest)

    code, _ = app.shorten(conn, "https://example.com/hello")
    assert app.resolve_and_log(conn, code, "10.0.0.2", '{"ua": "pytest"}') == "https://example.com/hello"
    assert app.resolve_and_log(conn, code, "2001:db8::1", '{"ua": "pytest"}') == "https://example.com/hello"
    stats = app.link_stats(conn, code)
    assert stats["clicks"] == 2
    assert stats["ips"] == ["::ffff:10.0.0.2", "2001:db8::1"]  # numeric order
    assert app.resolve_and_log(conn, "zzzzzz", "10.0.0.2", "{}") is None
    with pytest.raises(ValueError):
        app.shorten(conn, "javascript:alert(1)")
    with pytest.raises(pymysql.err.Error):  # the database itself refuses a non-JSON click note
        conn.cursor().execute(app.INSERT_CLICK, (stats["id"], "::ffff:1.2.3.4", "not json"))
    conn.rollback()
    demo.reset(conn.cursor())
    conn.commit()
