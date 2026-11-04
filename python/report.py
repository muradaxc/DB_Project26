"""Render the README's result tables (and the charts in docs/charts/) from results/*/*.json.

Each machine that ran python/run_all.py has a folder results/<label>/. The README's main tables
come from the "primary" machine named in results/primary.txt; the cross-machine table uses all.
Run:  python python/report.py           (rewrites the marked blocks in README.md, redraws charts)
      python python/report.py --check   (exit 1 if README.md is out of date; used by the tests)
"""
import argparse
import json
import pathlib
import re
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
README = ROOT / "README.md"
CHARTS = ROOT / "docs" / "charts"
NAMES = ("demo", "sizes", "migration", "features")


# ---------- loading ----------
def load_machine(folder):
    data = {}
    for name in NAMES:
        path = folder / f"{name}.json"
        if path.exists():
            data[name] = json.loads(path.read_text(encoding="utf-8"))
    return data


def load_all():
    machines = {}
    if RESULTS.exists():
        for folder in sorted(p for p in RESULTS.iterdir() if p.is_dir() and not p.name.endswith("-quick")):
            data = load_machine(folder)
            if data:
                machines[folder.name] = data
    primary = None
    marker = RESULTS / "primary.txt"
    if marker.exists():
        primary = marker.read_text(encoding="utf-8").strip()
    if primary not in machines:
        primary = next(iter(machines), None)
    return machines, primary


# ---------- formatting ----------
def ms(values, digits=2):
    """Median with the range: robust to the occasional stalled run (raw times stay in the JSON)."""
    return f"{statistics.median(values):.{digits}f} ({min(values):.{digits}f}–{max(values):.{digits}f})"


def mean(values):  # the typical run: the median, see ms()
    return statistics.median(values)


def num(n):
    return f"{n:,}"


def env_line(data):
    env = next(iter(data.values()))["environment"]
    return (f"MariaDB {env['mariadb_version']}, {env['os']}, {env['cpu_count']} CPUs, "
            f"Python {env['python']}, measured {env['measured_at_utc'][:10]}")


def source(label, data, name):
    if name not in data:
        return None
    s = data[name]["settings"]
    extra = ", ".join(f"{k}={v}" for k, v in s.items())
    return f"<sub>Source: `results/{label}/{name}.json` ({extra}). {env_line({name: data[name]})}.</sub>"


# ---------- blocks ----------
def block_glance(label, data):
    rows = []
    if "demo" in data:
        d = data["demo"]["results"]
        m, l = mean(d["insert_seconds"]["modern"]), mean(d["insert_seconds"]["legacy"])
        rows.append(("Link inserts with `RETURNING` vs. insert + `SELECT`",
                     f"**{l / m:.1f}× faster** ({m:.1f} s vs {l:.1f} s, 1 vs 2 queries per insert)"))
    if "sizes" in data:
        v = data["sizes"]["results"]["id_variants"]
        c, u = v["CHAR(36), UUID()"]["table_bytes"], v["UUID type, UUID()"]["table_bytes"]
        rows.append(("`UUID` type vs `CHAR(36)` (primary key table)", f"**{(1 - u / c) * 100:.0f}% smaller**"))
    if "migration" in data:
        a = data["migration"]["results"]["alter_seconds"]
        rows.append(("`ADD COLUMN` with `ALGORITHM=INSTANT` vs `COPY`",
                     f"**{mean(a['ADD COLUMN, COPY']) / mean(a['ADD COLUMN, INSTANT']):.0f}× faster**"))
    if "features" in data:
        f = data["features"]["results"]
        r = f["rerun_schema"]
        rows.append(("Reader errors while the schema is re-run "
                     f"({r['reruns']}×): `DROP`+`CREATE` vs `CREATE OR REPLACE`",
                     f"**{r['DROP IF EXISTS + CREATE']['reader_errors']} vs "
                     f"{r['CREATE OR REPLACE']['reader_errors']}**"))
        j = f["json_validation"]
        rows.append(("Bad JSON documents stored when a 2nd client skips the app",
                     f"**{j['bad_docs_stored']['app_validation']} vs {j['bad_docs_stored']['db_check']}** "
                     f"(app check vs `{j['constraint'].split(' (')[0]}` constraint)"))
        cte = f["cte_dml"]
        if cte["cte_supported"] and cte["DELETE"]["CTE (12.3+)"] != "unsupported":
            app_ = cte["DELETE"]["in the application"]
            c = cte["DELETE"]["CTE (12.3+)"]
            rows.append((f"Deleting {num(cte['stale_links'])} stale links: app loop vs `WITH … DELETE`",
                         f"**{app_['mean'] / c['mean']:.0f}× faster**, {num(app_['statements'])} vs 1 statements"))
    out = ["| Result | Measured |", "|---|---|"] + [f"| {a} | {b} |" for a, b in rows]
    out.append("")
    out.append(f"<sub>Primary machine: `{label}` ({env_line(data)}). Medians of the measured runs; "
               "ranges below.</sub>")
    return "\n".join(out)


def block_insert(label, data):
    if "demo" not in data:
        return "_Not measured yet: run `python python/run_all.py`._"
    d = data["demo"]["results"]
    s = data["demo"]["settings"]
    m, l = d["insert_seconds"]["modern"], d["insert_seconds"]["legacy"]
    b = d["table_bytes"]
    out = [
        "| Comparison | Modern | Legacy |", "|---|---|---|",
        f"| Queries per link insert | {d['queries_per_insert']['modern']:.0f} | {d['queries_per_insert']['legacy']:.0f} |",
        f"| Time for {num(s['rows'])} inserts, median (min–max) (s) | {ms(m)} | {ms(l)} |",
        f"| `links` table size (bytes) | {num(b['links'])} | {num(b['links_legacy'])} |",
        f"| `clicks` table size (bytes) | {num(b['clicks'])} | {num(b['clicks_legacy'])} |",
        "| IP sort order | numeric (correct) | text (wrong: `10.0.0.10` before `10.0.0.2`) |",
        "", source(label, data, "demo"),
    ]
    return "\n".join(out)


def block_migration(label, data):
    if "migration" not in data:
        return "_Not measured yet._"
    r = data["migration"]["results"]
    out = ["| Change | median (min–max) (s) |", "|---|---|"]
    for change, times in r["alter_seconds"].items():
        out.append(f"| {change} | {ms(times, 3)} |")
    p = r["progress"]
    out += ["", f"**Progress reporting.** During one `ALTER TABLE … FORCE, ALGORITHM=COPY` of "
            f"{num(p['rows'])} rows ({p['rebuild_seconds']:.2f} s), a second connection read "
            f"**{len(p['samples'])} progress values** from `information_schema.PROCESSLIST`"
            + (f", rising from {p['samples'][0]['progress_pct']:.1f}% to {p['samples'][-1]['progress_pct']:.1f}%"
               if p["samples"] else "") + ". Without it the only option is to wait.",
            "", source(label, data, "migration")]
    return "\n".join(out)


def block_sizes(label, data):
    if "sizes" not in data:
        return "_Not measured yet._"
    r = data["sizes"]["results"]
    out = ["| Column type | Table size (bytes) |", "|---|---|"]
    out += [f"| {k} | {num(v)} |" for k, v in r["ip_table_bytes"].items()]
    out += ["", "| Identifier variant | Load time median (min–max) (s) | Table size (bytes) |", "|---|---|---|"]
    out += [f"| {k} | {ms(v['load_seconds'])} | {num(v['table_bytes'])} |" for k, v in r["id_variants"].items()]
    out += ["", source(label, data, "sizes")]
    return "\n".join(out)


def block_features(label, data):
    if "features" not in data:
        return "_Not measured yet._"
    f = data["features"]["results"]
    j, r, c, g = f["json_validation"], f["rerun_schema"], f["cte_dml"], f["global_temporary"]
    out = [
        f"**1. Validation in the app vs. in the database** (`{j['constraint']}`)", "",
        "| | App validates (`json.loads`) | Database validates (`CHECK`) |", "|---|---|---|",
        f"| {num(j['rows'])} good inserts (s) | {j['insert_seconds']['app_validation']:.2f} | "
        f"{j['insert_seconds']['db_check']:.2f} |",
        f"| {j['bad_docs_from_second_client']} bad documents from a 2nd client: stored | "
        f"{j['bad_docs_stored']['app_validation']} | {j['bad_docs_stored']['db_check']} |",
        "",
        f"**2. Re-running the schema {r['reruns']} times while another connection reads the table**", "",
        "| | Statements per re-run | Time (s) | Reader: ok reads | Reader: errors |", "|---|---|---|---|---|",
    ]
    for mode in ("DROP IF EXISTS + CREATE", "CREATE OR REPLACE"):
        x = r[mode]
        codes = ", ".join(f"{n}× error {code}" for code, n in x["error_codes"].items()) or "none"
        out.append(f"| `{mode}` | {x['statements_per_rerun']} | {x['seconds']:.2f} | {num(x['reader_ok'])} | "
                   f"{num(x['reader_errors'])} ({codes}) |")
    out += ["", f"**3. `UPDATE` / `DELETE` driven by another query** ({num(c['links'])} links, "
            f"{num(c['stale_links'])} of them never clicked)", "",
            "| Statement | Way | Statements sent | Time, median (min–max) (s) |", "|---|---|---|---|"]
    for kind in ("UPDATE", "DELETE"):
        for way, x in c[kind].items():
            if x == "unsupported":
                out.append(f"| {kind} | {way} | – | not supported on this version |")
            else:
                out.append(f"| {kind} | {way} | {num(x['statements'])} | {ms([*x['runs']], 3)} |")
    out += ["", f"**4. A per-session scratch table** ({g['sessions']} sessions × {g['rows_per_session']} rows)",
            "", "| Way | DDL per session | Time (s) | Each session saw only its own rows |", "|---|---|---|---|"]
    for way in ("CREATE TEMPORARY TABLE per session", "GLOBAL TEMPORARY TABLE (12.3+)"):
        x = g[way]
        if x == "unsupported":
            out.append(f"| {way} | – | – | not supported on this version |")
        else:
            out.append(f"| {way} | {x['ddl_statements_per_session']} | {x['seconds']:.2f} | "
                       f"{'yes' if x['each_session_saw_only_its_own_rows'] else 'NO'} |")
    out += ["", source(label, data, "features")]
    return "\n".join(out)


def block_machines(machines):
    if not machines:
        return "_No results yet._"
    out = ["| Machine | MariaDB | OS | Inserts modern / legacy (s) | `UUID` vs `CHAR(36)` table | "
           "ADD COLUMN INSTANT / COPY (s) | `CREATE OR REPLACE` reader errors | CTE DML | Global temp. tables |",
           "|---|---|---|---|---|---|---|---|---|"]
    for label, data in machines.items():
        env = next(iter(data.values()))["environment"]
        cells = [f"`{label}`", env["mariadb_version"].split("-")[0], env["os"].split("-")[0]]
        if "demo" in data:
            d = data["demo"]["results"]["insert_seconds"]
            cells.append(f"{mean(d['modern']):.2f} / {mean(d['legacy']):.2f}")
        else:
            cells.append("–")
        if "sizes" in data:
            v = data["sizes"]["results"]["id_variants"]
            cells.append(f"{num(v['UUID type, UUID()']['table_bytes'])} vs {num(v['CHAR(36), UUID()']['table_bytes'])}")
        else:
            cells.append("–")
        if "migration" in data:
            a = data["migration"]["results"]["alter_seconds"]
            cells.append(f"{mean(a['ADD COLUMN, INSTANT']):.3f} / {mean(a['ADD COLUMN, COPY']):.3f}")
        else:
            cells.append("–")
        if "features" in data:
            f = data["features"]["results"]
            cells.append(str(f["rerun_schema"]["CREATE OR REPLACE"]["reader_errors"]))
            cells.append("yes" if f["cte_dml"]["cte_supported"] else "no")
            cells.append("no" if f["global_temporary"]["GLOBAL TEMPORARY TABLE (12.3+)"] == "unsupported" else "yes")
        else:
            cells += ["–", "–", "–"]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def render_blocks(machines, primary):
    data = machines.get(primary, {})
    return {
        "glance": block_glance(primary, data) if data else "_No results yet._",
        "insert": block_insert(primary, data),
        "migration": block_migration(primary, data),
        "sizes": block_sizes(primary, data),
        "features": block_features(primary, data),
        "machines": block_machines(machines),
    }


def apply_blocks(text, blocks):
    for name, body in blocks.items():
        pattern = re.compile(rf"(<!-- BEGIN:{name} -->).*?(<!-- END:{name} -->)", re.S)
        if not pattern.search(text):
            raise SystemExit(f"README.md has no <!-- BEGIN:{name} --> / <!-- END:{name} --> block")
        text = pattern.sub(lambda m: m.group(1) + "\n" + body + "\n" + m.group(2), text)
    return text


# ---------- charts ----------
BLUE, ORANGE = "#2a78d6", "#eb6834"  # validated pair (colour-blind safe, 3:1 on the surface)
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"


def _style(ax, title, xlabel):
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    multi = ax.get_legend() is not None
    ax.set_title(title, loc="left", color=INK, fontsize=12, fontweight="bold", pad=26 if multi else 12)
    ax.set_xlabel(xlabel, color=INK2, fontsize=9)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _bars(ax, labels, series, fmt):
    """Horizontal bars; series = [(name, colour, values)]; values labelled at the bar end."""
    import numpy as np
    n = len(series)
    height = 0.8 / n
    y = np.arange(len(labels))
    top = max(v for _, _, vals in series for v in vals) or 1
    for i, (name, colour, vals) in enumerate(series):
        pos = y - 0.4 + height * (i + 0.5)
        ax.barh(pos, vals, height=height - 0.04, color=colour, label=name)
        for p, v in zip(pos, vals):
            ax.text(v + top * 0.01, p, fmt(v), va="center", fontsize=8.5, color=INK2)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, top * 1.18)
    if n > 1:
        ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="lower left", bbox_to_anchor=(0, 1.0),
                  ncol=n, borderaxespad=0.2, handlelength=1.2)


def draw_charts(machines, primary):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed: charts skipped (pip install -r requirements-dev.txt)")
        return
    CHARTS.mkdir(parents=True, exist_ok=True)
    data = machines.get(primary, {})

    demo_machines = [(k, v) for k, v in machines.items() if "demo" in v]
    if demo_machines:
        fig, ax = plt.subplots(figsize=(8, 1.2 + 0.9 * len(demo_machines)))
        labels = [k for k, _ in demo_machines]
        _bars(ax, labels, [
            ("Modern: INSERT … RETURNING (1 query)", BLUE,
             [mean(v["demo"]["results"]["insert_seconds"]["modern"]) for _, v in demo_machines]),
            ("Legacy: INSERT + SELECT (2 queries)", ORANGE,
             [mean(v["demo"]["results"]["insert_seconds"]["legacy"]) for _, v in demo_machines]),
        ], lambda v: f"{v:.2f} s")
        _style(ax, "Time to insert the links, median of the measured runs (lower is better)", "seconds")
        fig.tight_layout()
        fig.savefig(CHARTS / "inserts.png", dpi=150)
        plt.close(fig)

    if "sizes" in data:
        v = data["sizes"]["results"]["id_variants"]
        fig, ax = plt.subplots(figsize=(8, 0.6 + 0.55 * len(v)))
        _bars(ax, list(v), [("table size", BLUE, [x["table_bytes"] / 1e6 for x in v.values()])],
              lambda x: f"{x:.1f} MB")
        _style(ax, "Primary-key table size by identifier type (lower is better)", "MB")
        fig.tight_layout()
        fig.savefig(CHARTS / "identifiers.png", dpi=150)
        plt.close(fig)

    if "migration" in data:
        a = data["migration"]["results"]["alter_seconds"]
        kinds = ["ADD COLUMN", "DROP COLUMN", "MODIFY COLUMN (widen)"]
        fig, ax = plt.subplots(figsize=(8, 2.6))
        _bars(ax, kinds, [
            ("ALGORITHM=INSTANT", BLUE, [mean(a[f"{k}, INSTANT"]) for k in kinds]),
            ("ALGORITHM=COPY", ORANGE, [mean(a[f"{k}, COPY"]) for k in kinds]),
        ], lambda x: f"{x:.3f} s")
        _style(ax, f"Schema change on {num(data['migration']['settings']['rows'])} rows (lower is better)",
               "seconds")
        fig.tight_layout()
        fig.savefig(CHARTS / "alter.png", dpi=150)
        plt.close(fig)

        samples = data["migration"]["results"]["progress"]["samples"]
        if samples:
            fig, ax = plt.subplots(figsize=(8, 2.6))
            ax.plot([s["t"] for s in samples], [s["progress_pct"] for s in samples], color=BLUE, linewidth=2,
                    marker="o", markersize=3)
            _style(ax, "Progress of an ALTER … ALGORITHM=COPY, read live by a 2nd connection",
                   "seconds since the ALTER started")
            ax.grid(axis="y", color=GRID, linewidth=0.8)
            ax.set_ylabel("% done", color=INK2, fontsize=9)
            ax.set_ylim(0, 105)
            fig.tight_layout()
            fig.savefig(CHARTS / "progress.png", dpi=150)
            plt.close(fig)
    print("Charts written to", CHARTS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="only check that README.md is up to date")
    parser.add_argument("--no-charts", action="store_true")
    args = parser.parse_args()
    machines, primary = load_all()
    text = README.read_text(encoding="utf-8")
    new = apply_blocks(text, render_blocks(machines, primary))
    if args.check:
        if new != text:
            print("README.md result tables are out of date: run python python/report.py")
            sys.exit(1)
        print("README.md matches results/")
        return
    README.write_text(new, encoding="utf-8")
    print(f"README.md tables updated from results/ (primary machine: {primary})")
    if not args.no_charts:
        draw_charts(machines, primary)


if __name__ == "__main__":
    main()
