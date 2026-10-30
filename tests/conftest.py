import os
import pathlib
import sys
import time

import pymysql
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import demo  # noqa: E402  (needs the path line above)


def run_sql_file(cur, path):
    """Run a .sql file made of plain statements separated by semicolons."""
    for chunk in path.read_text().split(";"):
        lines = [line for line in chunk.splitlines() if not line.strip().startswith("--")]
        statement = "\n".join(lines).strip()
        if statement:
            cur.execute(statement)


@pytest.fixture(scope="session")
def conn():
    """A connection to a database with the project's schema loaded."""
    deadline = time.time() + 90
    while True:
        try:
            connection = demo.connect()
            break
        except pymysql.err.Error:
            if time.time() > deadline:
                raise
            time.sleep(2)
    cur = connection.cursor()
    for name in ("01_modern.sql", "02_legacy.sql"):
        run_sql_file(cur, ROOT / "sql" / name)
    connection.commit()
    yield connection
    connection.close()


@pytest.fixture()
def cur(conn):
    cursor = conn.cursor()
    demo.reset(cursor)
    conn.commit()
    yield cursor
    conn.rollback()
