A project for area 1, "SQL that saves you work" for the [MariaDB student database projects, 2026-09](https://mariadb.org/bachelor_hackathon_2026-09/).

# DB_Project26: a link shortener built twice, with and without MariaDB's newer SQL features

![tests](https://github.com/muradaxc/DB_Project26/actions/workflows/ci.yml/badge.svg)

**Team:** Mahammad Ismayilov ([@Mago06-bit](https://github.com/Mago06-bit)), Murad Jafarov ([@muradaxc](https://github.com/muradaxc)), Muhammed Abdullayev
**MariaDB version developed against:** 13.0.2 (official `mariadb` Docker image, run on Docker Desktop / Windows 11)

## What this is and what we found

We model a small link shortener (links, plus a log of clicks) **twice**: a *modern* version that uses
MariaDB features, and a *legacy* version that does the same job without them. Then we compare them.

Features used in the main comparison: `UUID`, `INET6`, `RETURNING`, `CREATE OR REPLACE`.
Also covered in `python/` and `examples/`: `INET4`, `CREATE SEQUENCE`, `INTERSECT`/`EXCEPT`, invisible
columns, `IS JSON`, and instant `ALTER TABLE` (`ALGORITHM=INSTANT`).

Main result (`python python/demo.py`, MariaDB 13.0.2, 20,000 link inserts per run, 1 warm-up run
discarded, 5 measured runs):

| Comparison | Modern | Legacy |
|---|---|---|
| Queries per link insert | 1 | 2 |
| Time for 20000 inserts, mean ± sd (s) | 21.32 ± 0.77 | 42.11 ± 1.18 |
| Time, min–max (s) | 20.85–22.69 | 40.88–43.60 |
| `links` table size (bytes) | 1,589,248 | 3,686,400 |
| `clicks` table size (bytes) | 3,178,496 | 5,275,648 |
| IP sort order | numeric (correct) | text (wrong: `10.0.0.10` before `10.0.0.2`) |

**In short:** `RETURNING` halves the round trips and the time (the legacy version needs a second
`SELECT` to read the server-set `created_at`). An earlier session on the same laptop gave
14.1 s vs 27.8 s (3 runs), so absolute times vary but the ~2x ratio held. The `UUID` type stores
ids in 16 bytes instead of 36, and `ALGORITHM=INSTANT` turns a ~0.7 s table rebuild into ~0.02 s
(see Extra measurements).

<details>
<summary>Full output of that run</summary>

```
MariaDB version: 13.0.2-MariaDB-ubu2604

Modern: one statement gave back: ('6eb2f402-d2db-11f1-a6c5-660dbbb92f31', datetime.datetime(2026, 10, 28, 14, 25, 32))
Legacy: needed a 2nd query to read created_at: (datetime.datetime(2026, 10, 28, 14, 25, 32),)
INET6 order  : ['::ffff:10.0.0.2', '::ffff:10.0.0.9', '::ffff:10.0.0.10', '::ffff:192.168.1.1', '2001:db8::1']
VARCHAR order: ['10.0.0.10', '10.0.0.2', '10.0.0.9', '192.168.1.1', '2001:db8::1']

Benchmark: 20000 link inserts, 1 warm-up run + 5 measured runs
  warm-up (discarded): modern 21.11s | legacy 41.03s
  run 1: modern 21.10s | legacy 40.88s
  run 2: modern 20.85s | legacy 41.33s
  run 3: modern 21.02s | legacy 41.64s
  run 4: modern 20.93s | legacy 43.60s
  run 5: modern 22.69s | legacy 43.11s
```
</details>

## Side by side

**Schema.** Modern (`sql/01_modern.sql`):

```sql
CREATE OR REPLACE TABLE links (
  id UUID DEFAULT UUID() PRIMARY KEY,
  target_url VARCHAR(2048) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Legacy (`sql/02_legacy.sql`):

```sql
DROP TABLE IF EXISTS links_legacy;          -- the "DROP IF EXISTS dance"
CREATE TABLE links_legacy (
  id CHAR(36) PRIMARY KEY,                  -- 36 bytes of text instead of a 16-byte UUID
  target_url VARCHAR(2048) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Inserting a link and getting its id and timestamp back.**

```python
# Modern: one query. The server makes the UUID and the timestamp and RETURNING sends them back.
cur.execute("INSERT INTO links (target_url) VALUES (%s) RETURNING id, created_at", (url,))
link_id, created_at = cur.fetchone()

# Legacy: two queries. We invent the id in Python, insert, then ask again for created_at.
new_id = str(uuid.uuid4())
cur.execute("INSERT INTO links_legacy (id, target_url) VALUES (%s, %s)", (new_id, url))
cur.execute("SELECT created_at FROM links_legacy WHERE id = %s", (new_id,))
```

## Data model

- `links(id UUID, target_url, created_at)`: one row per shortened link.
- `clicks(id, link_id UUID -> links.id, client_ip INET6, clicked_at)`: one row per visit.
- `links_legacy` / `clicks_legacy`: the same shape with `CHAR(36)` ids and `VARCHAR(45)` IPs.

Why it looks like this :

- **UUID ids instead of auto-increment.** Short-link ids are visible to users, so sequential numbers
  would let anyone count or guess other links. UUIDs can also be made on any server without
  coordination. The cost is a bigger key (16 bytes vs 4-8), which the `UUID` type keeps far below the
  36 bytes of `CHAR(36)`.
- **`INET6` instead of `INET4`.** Visitors can arrive over IPv4 or IPv6, and `INET4` cannot hold IPv6.
  `INET6` holds both (IPv4 as `::ffff:a.b.c.d`) and sorts and compares them as addresses, not text.
- **A separate `clicks` table.** One link gets many clicks. Keeping clicks in their own table with a
  foreign key to `links` avoids repeating the URL on every click and makes per-link counts a simple
  `GROUP BY`.
- **`created_at` set by the server.** The database clock is the single source of truth, which is
  exactly the value the legacy version has to fetch with a second query.

## How to run it

Requirements: Docker (running), Git, Python 3.10+.

```
git clone https://github.com/muradaxc/DB_Project26.git
cd DB_Project26
cp .env.example .env              # Windows: copy .env.example .env
# edit .env and set the passwords (it is git-ignored)

docker compose up -d --wait       # starts MariaDB and loads sql/*.sql; --wait blocks until it is healthy

python -m venv .venv
# activate it:  Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python python/demo.py             # full run (about 5 minutes); quick check: python python/demo.py --rows 2000 --runs 2
python python/sizes.py            # storage comparison: VARCHAR vs INET6 vs INET4, CHAR(36) vs UUID types
python python/migration.py        # schema-change timing: ALGORITHM=INSTANT vs COPY
pip install -r requirements-dev.txt && pytest -q     # tests
```

Reset everything: `docker compose down -v`, then `docker compose up -d --wait`.
The image is pinned to `mariadb:13.0.2` (change `MARIADB_TAG` in `.env` to try another version).

The script connects as a limited user (`DB_USER`) that only has rights on the `shortener` database,
not as root, and no password is stored in the repository.

### Paste-ready examples

`examples/` has one small SQL file per feature that you can run against any MariaDB (each creates and
drops its own `demo_*` tables). With the compose setup running:

```
docker compose exec db mariadb -u app -p shortener      # enter DB_PASSWORD when asked
MariaDB [shortener]> source /examples/01_uuid.sql
```
Files: `01_uuid.sql`, `02_inet.sql`, `03_returning.sql`, `04_create_or_replace.sql`, `05_sequence.sql`,
`06_set_operations.sql`, `07_invisible_column.sql`, `08_is_json.sql`.
`08_is_json.sql` needs a MariaDB version that supports `IS JSON`: it works on 13.0.2 and is a syntax
error on 10.11. All eight files ran without errors on 13.0.2.

## Extra measurements

Run these and paste the tables they print. Both repeat runs after a warm-up and report mean ± standard
deviation.

**Schema changes on a table that already has rows** (`python/migration.py`, default 500,000 rows):
`ADD COLUMN` / `DROP COLUMN` with `ALGORITHM=INSTANT` against `ALGORITHM=COPY`.

| Change | mean ± sd (s) | min–max (s) |
|---|---|---|
| ADD COLUMN, INSTANT | 0.021 ± 0.000 | 0.021–0.021 |
| DROP COLUMN, INSTANT | 0.055 ± 0.008 | 0.049–0.064 |
| ADD COLUMN, COPY | 0.696 ± 0.028 | 0.663–0.713 |
| DROP COLUMN, COPY | 0.677 ± 0.040 | 0.643–0.720 |

1 warm-up round discarded, 3 measured rounds. INSTANT only changes metadata, so its time does not
grow with the table; COPY rewrites all 500,000 rows and would keep growing with more data.

**Storage** (`python/sizes.py`, default 200,000 rows, loaded server-side):

| Column type | Table size (bytes) |
|---|---|
| VARCHAR(45) | 8,929,280 |
| INET6 | 8,929,280 |
| INET4 | 6,832,128 |

| Identifier variant | Load time mean ± sd (s) | Table size (bytes) |
|---|---|---|
| CHAR(36), UUID() | 0.87 ± 0.35 | 12,124,160 |
| UUID type, UUID() | 0.43 ± 0.01 | 7,880,704 |
| UUID type, UUID_v4() | 0.89 ± 0.12 | 12,075,008 |
| UUID type, UUID_v7() | 0.63 ± 0.03 | 7,880,704 |

The `UUID` type saves about 4.2 MB at 200,000 rows with ordered ids, which matches the 20 bytes per
row it saves (16 instead of 36). With random `UUID_v4()` ids the saving disappears: the table is as
large as the `CHAR(36)` one and loads twice as slowly. Our likely explanation is that random primary
keys are inserted all over the index, splitting pages and leaving them part-empty, while `UUID()`
(which MariaDB stores time-ordered) and `UUID_v7()` append at the end. So pick `UUID_v7()` (or
`UUID()`) over `UUID_v4()` for primary keys.

## Tests and CI

`tests/` has pytest tests that check the claims this README makes: `RETURNING` hands back the id and
timestamp, `INET6` sorts numerically while `VARCHAR` does not, plain IPv4 text in `INET6` is either rejected or stored mapped, and the
schema script can be re-run. `.github/workflows/ci.yml` starts a MariaDB service container and runs
them (plus a small smoke run of `demo.py`) on every push; the badge at the top shows the result.

## How it was made

- `sql/01_modern.sql`: schema using the features. `sql/02_legacy.sql`: the same schema the old way.
- `python/demo.py`: two small demos (RETURNING, IP sorting), then a benchmark. It does 1 warm-up run
  (discarded) plus several measured runs of N link inserts per version, committing once per run so the
  difference comes from round trips rather than disk flushes. All SQL is fixed strings with `%s`
  parameters, never built from variables.
- The benchmark reports mean, standard deviation and min/max, plus queries per insert and table sizes.
- `python/sizes.py` and `python/migration.py` are separate measurements (storage and schema changes);
  large test tables are generated on the server with MariaDB's built-in `seq_1_to_N` sequence tables.

**Use of AI.** Parts of this project (the first version of the compose file, SQL, benchmark script and
README drafts) were created with help from Claude (Anthropic), which our course allows. We chose the
topic and the app, ran every script and test on our own machine (MariaDB 13.0.2 in Docker on
Windows 11), and checked the results; the numbers in this README come from those runs.

**Team responsibilities.**
- Mahammad Ismayilov: Docker and Python setup; local MariaDB measurements and tests; checking
  feature compatibility and documenting the results.
- Murad Jafarov: repository owner; responsible for publishing the project to `main` in stages
  and verifying the GitHub Actions workflow after the push.
- Muhammed Abdullayev: responsible for validating the instructions from a fresh clone on a
  separate machine and running the SQL examples.

The publishing, CI verification, and fresh-clone checks should be marked as completed only
after each person has actually performed them.

## Findings worth knowing

- **Behaviour changes between versions.** We first tested on 10.11 and then ran on 13.0.2:
  - `UPDATE ... RETURNING`: syntax error on 10.11, works on 13.0.2.
  - `IS JSON`: syntax error on 10.11, works on 13.0.2.
  - `UUID_v4()` / `UUID_v7()`: exist on 13.0.2.
  - Plain IPv4 text such as `10.0.0.2` in an `INET6` column: rejected on 10.11; accepted on 13.0.2 and stored as `::ffff:10.0.0.2`.
    Our code writes IPv4 as `::ffff:10.0.0.2`, which works on both. `INET4` takes plain IPv4 but
    cannot hold IPv6.
- **Random UUIDs cost space and time** as primary keys (see the identifier table above), so the
  `UUID` type's saving depends on the ids being time-ordered.
- `CREATE OR REPLACE TABLE` is not magic when tables point at each other. Re-running the schema script
  failed with error 1451 once `clicks` referenced `links`, so `sql/01_modern.sql` switches
  `FOREIGN_KEY_CHECKS` off while it replaces them. The legacy script avoids that by dropping the child
  table first, so the "no DROP dance" benefit is real but needs care with foreign keys.
- `INET6` is **not smaller than text for IPv4 data**: it always takes 16 bytes, while an IPv4 string is
  about 7-15 characters. In our run VARCHAR(45) and INET6 tables were the same size; `INET4` (4 bytes) was
  smaller. The type pays off for sorting and comparing, and for IPv6, not for IPv4 storage. The UUID type
  did save space against `CHAR(36)`.
- Table sizes from `information_schema` are estimates and were unreliable for small tables (every table
  looked identical at 20,000 rows). Use 100,000+ rows for size numbers.
- Confounder: legacy ids come from Python's random `uuid4()`, modern ids from the server's `UUID()`
  (time-based). The identifier table shows random ids alone make a table bigger, so part of the
  `links` size gap in the main table comes from that, not only from `CHAR(36)`. The clean
  type-only comparison is `CHAR(36), UUID()` vs `UUID type, UUID()` in `sizes.py`.
- Table sizes come from `information_schema` and InnoDB allocates in 16 KB pages, so treat them as
  rough.

## When is each feature worth it? 

| Feature | Worth reaching for when | Not worth it / watch out |
|---|---|---|
| `UUID` | ids are made by the database or shared across systems; 16 bytes vs 36 | you need small sequential integers; random `UUID_v4()` primary keys cancel the space saving (use `UUID_v7()`) |
| `INET6` / `INET4` | you sort or compare IP addresses, or store IPv6 | you only want to save space on IPv4 (INET6 is no smaller than text there; INET4 is); other tools expect plain strings |
| `RETURNING` | you need server-made values (ids, defaults) right after an insert, update or delete | `UPDATE ... RETURNING` is missing on older versions such as 10.11 |
| `CREATE OR REPLACE` | setup, test and migration scripts that must be re-runnable | tables holding data you want to keep (it drops them); tables with foreign keys need extra care |
| `ALGORITHM=INSTANT` | adding or dropping a column on a big table | changes it does not support still fall back to a full rebuild |

## Limitations (what this does not measure)

- One machine, one client, one connection: no concurrency, no network between app and database.
- Docker Desktop on Windows adds overhead of its own; absolute numbers will differ elsewhere.
- Small data (tens of thousands of rows), so no statement about very large tables.
- Size numbers are InnoDB estimates; migration timings are for one table shape on one machine.
- Only the features above. No redirect web server: the "app" is the database layer plus scripts,
  because the comparison is about SQL, not HTTP.
- No `UUID()` vs `uuid4()` control run: the legacy and modern ids come from different generators (see
  Findings).
