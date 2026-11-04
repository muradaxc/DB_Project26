"""Save measurement results as JSON, with the environment they were measured in.

Every measurement script calls save(...) when it is given --json PATH. The files under results/
are the source of truth for the numbers in the README (python/report.py renders the tables from
them, and tests/test_readme_matches_results.py checks that the README still matches).
"""
import datetime
import json
import os
import pathlib
import platform
import sys


def environment(cur):
    cur.execute("SELECT VERSION()")
    version = cur.fetchone()[0]
    return {
        "mariadb_version": version,
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
        "measured_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def save(path, cur, args, results):
    if not path:
        return
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "environment": environment(cur),
        "settings": {k: v for k, v in vars(args).items() if k != "json"},
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nSaved {path}")
