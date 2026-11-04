"""Take screenshots of the running web app for the README (optional).

Needs Playwright:  pip install playwright  and  python -m playwright install chromium
Start the app first (python python/app.py --demo-data), then run:  python python/screenshots.py
"""
import argparse
import pathlib
import re

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1000, "height": 900})
        page.goto(args.base + "/")
        page.screenshot(path=str(OUT / "home.png"), full_page=True)
        # open the stats page of the link with the most clicks
        rows = page.locator("table tr").all()[1:]
        best = max(rows, key=lambda r: int(r.locator("td").nth(2).inner_text() or 0))
        code = re.sub(r"^/stats/", "", best.locator("a").first.get_attribute("href"))
        page.goto(args.base + f"/stats/{code}")
        page.screenshot(path=str(OUT / "stats.png"), full_page=True)
        browser.close()
    print("Saved", OUT / "home.png", "and", OUT / "stats.png")


if __name__ == "__main__":
    main()
