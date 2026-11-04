"""A small, working link shortener on top of sql/03_app.sql. No extra packages needed.

Start it from the repository root:   python python/app.py
Then open http://127.0.0.1:8000 in a browser, shorten a link, open the short link, and look at
its statistics page. Every page shows the SQL it ran.
"""
import argparse
import html
import json
import string
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pymysql

from demo import connect, to_inet6

ALPHABET = string.digits + string.ascii_letters  # base62: short codes like "q0U"

# Fixed statements only. Values are passed as parameters, never built into the SQL.
INSERT_LINK = "INSERT INTO app_links (target_url, created_from) VALUES (%s, %s) RETURNING code, created_at"
FIND_LINK = "SELECT id, target_url FROM app_links WHERE code = %s"
INSERT_CLICK = "INSERT INTO app_clicks (link_id, client_ip, meta) VALUES (%s, %s, %s)"
LINK_SUMMARY = (
    "SELECT l.id, l.target_url, l.created_at, COUNT(c.id), COUNT(DISTINCT c.client_ip) "
    "FROM app_links l LEFT JOIN app_clicks c ON c.link_id = l.id WHERE l.code = %s GROUP BY l.id"
)
LINK_IPS = "SELECT DISTINCT client_ip FROM app_clicks WHERE link_id = %s ORDER BY client_ip"
LINK_RECENT = (
    "SELECT clicked_at, client_ip, JSON_VALUE(meta, '$.user_agent') FROM app_clicks "
    "WHERE link_id = %s ORDER BY clicked_at DESC, id DESC LIMIT 10"
)
RECENT_LINKS = (
    "SELECT l.code, l.target_url, l.created_at, COUNT(c.id) FROM app_links l "
    "LEFT JOIN app_clicks c ON c.link_id = l.id GROUP BY l.id ORDER BY l.created_at DESC, l.code DESC LIMIT 15"
)
VERSION = "SELECT VERSION()"


def encode(number):
    out = ""
    while True:
        number, rest = divmod(number, 62)
        out = ALPHABET[rest] + out
        if number == 0:
            return out


def decode(code):
    if not code or len(code) > 11 or any(ch not in ALPHABET for ch in code):
        return None
    number = 0
    for ch in code:
        number = number * 62 + ALPHABET.index(ch)
    return number


def valid_url(url):
    parts = urllib.parse.urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc) and len(url) <= 2048


# ---------- database functions (also used by the tests) ----------
def shorten(conn, url, from_ip=None):
    if not valid_url(url):
        raise ValueError("Only http:// and https:// links up to 2048 characters can be shortened.")
    cur = conn.cursor()
    cur.execute(INSERT_LINK, (url, to_inet6(from_ip) if from_ip else None))  # 1 round trip
    code, created_at = cur.fetchone()
    conn.commit()
    return encode(code), created_at


def resolve_and_log(conn, code, ip, meta_json):
    number = decode(code)
    if number is None:
        return None
    cur = conn.cursor()
    cur.execute(FIND_LINK, (number,))
    row = cur.fetchone()
    if row is None:
        return None
    cur.execute(INSERT_CLICK, (row[0], to_inet6(ip), meta_json))
    conn.commit()
    return row[1]


def link_stats(conn, code):
    number = decode(code)
    if number is None:
        return None
    cur = conn.cursor()
    cur.execute(LINK_SUMMARY, (number,))
    row = cur.fetchone()
    if row is None:
        return None
    link_id, url, created_at, clicks, unique_ips = row
    cur.execute(LINK_IPS, (link_id,))
    ips = [r[0] for r in cur.fetchall()]
    cur.execute(LINK_RECENT, (link_id,))
    recent = cur.fetchall()
    return {"id": link_id, "url": url, "created_at": created_at, "clicks": clicks,
            "unique_ips": unique_ips, "ips": ips, "recent": recent}


DEMO_LINKS = (
    "https://mariadb.org/bachelor_hackathon_2026-09/",
    "https://mariadb.com/docs/server/reference/data-types/string-data-types/inet6",
    "https://github.com/muradaxc/DB_Project26",
)
# Documentation-only address ranges (RFC 5737 / RFC 3849), so no real person's IP is used.
DEMO_VISITORS = (
    ("192.0.2.10", "Mozilla/5.0 (Windows NT 10.0) Firefox/131.0"),
    ("192.0.2.9", "Mozilla/5.0 (X11; Linux x86_64) Chrome/130.0"),
    ("198.51.100.7", "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Safari/604.1"),
    ("192.0.2.100", "Mozilla/5.0 (Macintosh) Safari/605.1"),
    ("2001:db8::1", "Mozilla/5.0 (Android 15) Chrome/130.0"),
    ("192.0.2.10", "Mozilla/5.0 (Windows NT 10.0) Firefox/131.0"),
)


def seed_demo(conn):
    """Example links and clicks (clearly fake visitors) so the pages have something to show."""
    codes = [shorten(conn, url)[0] for url in DEMO_LINKS]
    for i, (ip, agent) in enumerate(DEMO_VISITORS):
        resolve_and_log(conn, codes[0], ip, json.dumps({"user_agent": agent, "referrer": ""}))
        if i % 2 == 0:
            resolve_and_log(conn, codes[1], ip, json.dumps({"user_agent": agent, "referrer": ""}))
    return codes


# ---------- web pages ----------
STYLE = """
body{font-family:system-ui,sans-serif;max-width:860px;margin:0 auto;padding:24px 16px;color:#1d2330;background:#f7f8fa}
h1{font-size:1.6rem;margin:0 0 4px} h2{font-size:1.1rem;margin-top:28px} a{color:#0b5cad}
.card{background:#fff;border:1px solid #dde1e7;border-radius:10px;padding:16px 18px;margin:14px 0}
form{display:flex;gap:8px;flex-wrap:wrap} input[type=url]{flex:1;min-width:220px;padding:10px;border:1px solid #c5cbd5;border-radius:8px;font-size:1rem}
button{padding:10px 16px;border:0;border-radius:8px;background:#0b5cad;color:#fff;font-size:1rem;cursor:pointer}
table{border-collapse:collapse;width:100%;font-size:.92rem} td,th{text-align:left;padding:6px 8px;border-bottom:1px solid #eceef2}
th{color:#5a6372;font-weight:600} code,pre{font-family:ui-monospace,Consolas,monospace;font-size:.85rem}
pre{background:#11151c;color:#d6e2f0;padding:12px;border-radius:8px;overflow-x:auto;white-space:pre-wrap}
.muted{color:#5a6372;font-size:.9rem} .big{font-size:1.8rem;font-weight:700} .stats{display:flex;gap:28px;flex-wrap:wrap}
.error{color:#a3201b}
"""


def page(title, body, sql, version):
    sql_block = "\n\n".join(html.escape(s) for s in sql)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>{STYLE}</style></head><body>
<h1><a href="/" style="color:inherit;text-decoration:none">DB_Project26 link shortener</a></h1>
<div class="muted">Built on MariaDB {html.escape(version)}: SEQUENCE short codes, UUID ids, INET6 visitor IPs,
IS JSON click data, INSERT ... RETURNING.</div>
{body}
<h2>SQL behind this page</h2><pre>{sql_block}</pre>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send_html(self, status, text):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, status, location):
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def version(self, conn):
        cur = conn.cursor()
        cur.execute(VERSION)
        return cur.fetchone()[0]

    def home(self, conn, error=""):
        cur = conn.cursor()
        cur.execute(RECENT_LINKS)
        rows = "".join(
            f"<tr><td><a href='/stats/{encode(code)}'>{encode(code)}</a></td>"
            f"<td>{html.escape(url[:70])}</td><td>{clicks}</td><td>{created}</td></tr>"
            for code, url, created, clicks in cur.fetchall()
        ) or "<tr><td colspan=4 class=muted>No links yet.</td></tr>"
        err = f"<p class=error>{html.escape(error)}</p>" if error else ""
        body = f"""<div class="card"><form method="post" action="/shorten">
<input type="url" name="url" placeholder="https://example.com/a/very/long/link" required>
<button type="submit">Shorten</button></form>{err}</div>
<h2>Recent links</h2><div class="card"><table><tr><th>Code</th><th>Target</th><th>Clicks</th><th>Created</th></tr>
{rows}</table></div>"""
        self.send_html(400 if error else 200, page("Link shortener", body, [RECENT_LINKS, INSERT_LINK],
                                                   self.version(conn)))

    def stats(self, conn, code):
        s = link_stats(conn, code)
        if s is None:
            self.send_html(404, page("Not found", "<p class=error>No such short link.</p>", [LINK_SUMMARY],
                                     self.version(conn)))
            return
        host = self.headers.get("Host", "127.0.0.1:8000")
        short = f"http://{host}/l/{code}"
        ips = "".join(f"<tr><td><code>{html.escape(ip)}</code></td></tr>" for ip in s["ips"]) or \
            "<tr><td class=muted>No visitors yet.</td></tr>"
        recent = "".join(
            f"<tr><td>{t}</td><td><code>{html.escape(ip)}</code></td><td>{html.escape((ua or '')[:60])}</td></tr>"
            for t, ip, ua in s["recent"]
        ) or "<tr><td colspan=3 class=muted>No clicks yet.</td></tr>"
        body = f"""<div class="card"><div class="muted">Short link</div>
<div style="font-size:1.25rem"><a href="/l/{code}">{html.escape(short)}</a></div>
<div class="muted" style="margin-top:6px">goes to {html.escape(s['url'])} · created {s['created_at']}</div></div>
<div class="card stats"><div><div class="big">{s['clicks']}</div><div class=muted>clicks</div></div>
<div><div class="big">{s['unique_ips']}</div><div class=muted>unique visitors</div></div></div>
<h2>Visitor IPs, sorted by INET6 (as addresses, not as text)</h2><div class="card"><table>{ips}</table></div>
<h2>Last 10 clicks (browser read with JSON_VALUE)</h2><div class="card"><table>
<tr><th>When</th><th>IP</th><th>Browser</th></tr>{recent}</table></div>"""
        self.send_html(200, page(f"Stats for {code}", body, [LINK_SUMMARY, LINK_IPS, LINK_RECENT],
                                 self.version(conn)))

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        conn = connect()
        try:
            if path == "/":
                self.home(conn)
            elif path.startswith("/l/"):
                meta = json.dumps({"user_agent": self.headers.get("User-Agent", ""),
                                   "referrer": self.headers.get("Referer", "")})
                target = resolve_and_log(conn, path[3:], self.client_address[0], meta)
                if target:
                    self.redirect(302, target)
                else:
                    self.send_html(404, page("Not found", "<p class=error>No such short link.</p>",
                                             [FIND_LINK], self.version(conn)))
            elif path.startswith("/stats/"):
                self.stats(conn, path[7:])
            else:
                self.send_html(404, page("Not found", "<p class=error>Page not found.</p>", [], self.version(conn)))
        finally:
            conn.close()

    def do_POST(self):
        conn = connect()
        try:
            if urllib.parse.urlsplit(self.path).path != "/shorten":
                self.send_html(404, page("Not found", "<p class=error>Page not found.</p>", [], self.version(conn)))
                return
            length = min(int(self.headers.get("Content-Length", 0)), 10_000)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            url = form.get("url", [""])[0].strip()
            try:
                code, _ = shorten(conn, url, self.client_address[0])
            except ValueError as exc:
                self.home(conn, str(exc))
                return
            self.redirect(303, f"/stats/{code}")
        except pymysql.err.Error as exc:
            self.send_html(500, f"Database error: {html.escape(str(exc))}")
        finally:
            conn.close()

    def log_message(self, fmt, *args):
        print("  " + fmt % args)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--demo-data", action="store_true", help="add example links and clicks first")
    args = parser.parse_args()
    if args.demo_data:
        conn = connect()
        print("Added example links:", ", ".join(seed_demo(conn)))
        conn.close()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Link shortener running on http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
