"""Run every test and measurement, save the results, and update the README and charts.

Run from the repository root, with the database running (docker compose up -d --wait):
    python python/run_all.py              full run (about 10 minutes on a laptop)
    python python/run_all.py --quick      small sizes, to check that everything works (1 minute)

Results go to results/<label>/ (label = operating system + MariaDB version, or --label).
Afterwards README.md's result tables and docs/charts/ are regenerated from all results/ folders.
If Playwright is installed, fresh screenshots of the web app are saved to docs/screenshots/.
"""
import argparse
import importlib.util
import pathlib
import platform
import re
import subprocess
import sys
import time

import pymysql

from demo import connect, wait_for_db

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable

FULL = {
    "demo": ["--rows", "20000", "--runs", "5"],
    "sizes": ["--rows", "200000", "--runs", "3"],
    "migration": ["--rows", "500000", "--runs", "3"],
    "features": ["--rows", "20000", "--runs", "3", "--reruns", "200", "--sessions", "100"],
}
QUICK = {
    "demo": ["--rows", "1000", "--runs", "2"],
    "sizes": ["--rows", "20000", "--runs", "2"],
    "migration": ["--rows", "50000", "--runs", "2"],
    "features": ["--rows", "1000", "--runs", "2", "--reruns", "30", "--sessions", "10"],
}


def run(args, **kw):
    print("\n$ " + " ".join(str(a) for a in args), flush=True)
    return subprocess.run(args, cwd=ROOT, **kw)


def run_sql_file(cur, path):
    for chunk in path.read_text(encoding="utf-8").split(";"):
        lines = [line for line in chunk.splitlines() if not line.strip().startswith("--")]
        statement = "\n".join(lines).strip()
        if statement:
            cur.execute(statement)


def ensure_schema():
    """Load sql/*.sql if the tables are missing (e.g. a CI database that docker compose did not set up)."""
    deadline = time.time() + 90
    while True:
        try:
            conn = connect()
            break
        except pymysql.err.Error:
            if time.time() > deadline:
                raise SystemExit("Cannot connect to MariaDB: is it running (docker compose up -d --wait)?")
            time.sleep(2)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() "
                "AND table_name = 'app_clicks'")
    if cur.fetchone()[0] == 0:
        print("Tables missing: loading sql/01_modern.sql, 02_legacy.sql, 03_app.sql")
        for name in ("01_modern.sql", "02_legacy.sql", "03_app.sql"):
            run_sql_file(cur, ROOT / "sql" / name)
        conn.commit()
    conn.close()


def screenshots():
    if importlib.util.find_spec("playwright") is None:
        print("\nPlaywright is not installed: screenshots skipped "
              "(pip install playwright && python -m playwright install chromium)")
        return
    conn = wait_for_db()
    run_sql_file(conn.cursor(), ROOT / "sql" / "03_app.sql")  # empty app tables, so the pictures are clean
    conn.commit()
    conn.close()
    app = subprocess.Popen([PY, "python/app.py", "--demo-data", "--port", "8765"], cwd=ROOT)
    try:
        time.sleep(3)
        run([PY, "python/screenshots.py", "--base", "http://127.0.0.1:8765"])
    finally:
        app.terminate()
        app.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="small sizes: checks that it works, numbers are not final")
    parser.add_argument("--label", help="results folder name (default: OS + MariaDB version)")
    parser.add_argument("--primary", action="store_true",
                        help="make this machine the source of the README's main tables (default for the first machine)")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--no-screenshots", action="store_true")
    args = parser.parse_args()

    ensure_schema()
    conn = wait_for_db()
    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    version = re.match(r"[\d.]+", cur.fetchone()[0]).group(0)
    conn.close()
    label = args.label or f"{platform.system().lower()}-mariadb-{version}"
    if args.quick:
        label += "-quick"
    out = ROOT / "results" / label
    out.mkdir(parents=True, exist_ok=True)
    print(f"MariaDB {version}. Results go to results/{label}/")

    failed = []
    if not args.skip_tests:
        result = run([PY, "-m", "pytest", "-q"], capture_output=True, text=True)
        print(result.stdout[-3000:], result.stderr[-2000:])
        (out / "pytest.txt").write_text(result.stdout, encoding="utf-8")
        if result.returncode != 0:
            failed.append("pytest")

    sizes = QUICK if args.quick else FULL
    for name, extra in sizes.items():
        result = run([PY, f"python/{name}.py", *extra, "--json", str(out / f"{name}.json")])
        if result.returncode != 0:
            failed.append(name)

    primary = ROOT / "results" / "primary.txt"
    if (args.primary or not primary.exists()) and not args.quick:
        primary.write_text(label + "\n", encoding="utf-8")
        print(f"\nresults/primary.txt -> {label} (the README's main tables come from this machine)")

    run([PY, "python/report.py"])
    if not args.no_screenshots:
        screenshots()

    print("\n" + ("All done." if not failed else f"Finished, but these steps failed: {', '.join(failed)}"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
