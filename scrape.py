#!/usr/bin/env python3
"""Scrape kworb.net (Spotify, iTunes, YouTube, Worldwide, Radio charts) into data/<section>/*.json."""
import json
import re
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://kworb.net"
HEADERS = {"User-Agent": "Mozilla/5.0 (kworb-net-api scraper)"}
OUT_DIR = Path(__file__).parent / "data"
DELAY = 0.5

# href like ".../artist/<id>.html", ".../artist/<id>_songs.html", ".../track/<id>.html", ".../video/<id>.html"
LINK_RE = re.compile(r'(?:^|/)(artist|track|video)/([^/]+?)(?:_[a-z]+)?\.html')


def fetch(path):
    url = path if path.startswith("http") else f"{BASE}{path}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


class TableParser(HTMLParser):
    """Extracts the first <table> on the page: header names, cell text, links and tr id per row."""

    def __init__(self):
        super().__init__()
        self.in_table = self.done = False
        self.section = None  # 'thead' | 'tbody'
        self.cur_row = None
        self.cur_row_id = None
        self.cur_cell_text = None
        self.cur_cell_links = None
        self.cur_link = None
        self.headers = []
        self.rows = []  # list of (row_id, [{"text": str, "links": [{"href","text"}]}])

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and not self.done:
            self.in_table = True
        elif not self.in_table:
            return
        elif tag in ("thead", "tbody"):
            self.section = tag
        elif tag == "tr":
            self.cur_row = []
            self.cur_row_id = attrs.get("id")
        elif tag in ("td", "th"):
            self.cur_cell_text = []
            self.cur_cell_links = []
        elif tag == "a" and self.cur_cell_links is not None:
            self.cur_link = {"href": attrs.get("href", ""), "text": []}

    def handle_endtag(self, tag):
        if not self.in_table:
            return
        if tag == "table":
            self.in_table = self.done = True
        elif tag == "tr" and self.cur_row is not None:
            if self.section == "thead":
                self.headers = [c["text"] for c in self.cur_row]
            elif self.section == "tbody":
                self.rows.append((self.cur_row_id, self.cur_row))
            self.cur_row = None
        elif tag in ("td", "th") and self.cur_cell_text is not None:
            text = " ".join("".join(self.cur_cell_text).split())
            self.cur_row.append({"text": text, "links": self.cur_cell_links})
            self.cur_cell_text = self.cur_cell_links = None
        elif tag == "a" and self.cur_link is not None:
            self.cur_link["text"] = " ".join("".join(self.cur_link["text"]).split())
            self.cur_cell_links.append(self.cur_link)
            self.cur_link = None

    def handle_data(self, data):
        if self.cur_cell_text is not None:
            self.cur_cell_text.append(data)
        if self.cur_link is not None:
            self.cur_link["text"].append(data)


def extract_ids(cells):
    ids, artist_ids = {}, []
    for cell in cells:
        for link in cell["links"]:
            m = LINK_RE.search(link["href"])
            if not m:
                continue
            kind, ident = m.group(1), m.group(2)
            if kind == "artist" and ident not in artist_ids:
                artist_ids.append(ident)
            elif kind in ("track", "video") and f"{kind}_id" not in ids:
                ids[f"{kind}_id"] = ident
    if artist_ids:
        ids["artist_ids"] = artist_ids
    return ids


def parse_table(html):
    parser = TableParser()
    parser.feed(html)
    seen, keys = {}, []
    for h in parser.headers:
        h = h or "col"
        seen[h] = seen.get(h, 0) + 1
        keys.append(h if seen[h] == 1 else f"{h}_{seen[h]}")
    chart = []
    for row_id, cells in parser.rows:
        row = dict(zip(keys, (c["text"] for c in cells)))
        row.update(extract_ids(cells))
        if row_id:
            row["row_id"] = row_id
        chart.append(row)
    title_match = re.search(r'pagetitle">(?:<strong>)?([^<|]+)', html)
    return chart, (title_match.group(1).strip() if title_match else None)


def scrape(category, name, path):
    out = OUT_DIR / category
    out.mkdir(parents=True, exist_ok=True)
    try:
        chart, title = parse_table(fetch(path))
    except Exception as e:
        print(f"SKIP {category}/{name}: {e}")
        return
    url = path if path.startswith("http") else f"{BASE}{path}"
    (out / f"{name}.json").write_text(
        json.dumps({"source": url, "title": title, "chart": chart}, ensure_ascii=False, indent=2)
    )
    print(f"{category}/{name}: {len(chart)} rows")
    time.sleep(DELAY)


def discover_spotify_countries():
    html = fetch("/spotify/")
    return sorted(set(re.findall(r'country/([a-z]+)_daily\.html', html)))


def discover_itunes_country_bases():
    html = fetch("/pop/")
    return sorted(set(re.findall(r'<option value="(/pop[a-z]*/)">', html)))


def main():
    for cc in discover_spotify_countries():
        scrape("spotify", f"{cc}_daily", f"/spotify/country/{cc}_daily.html")
        scrape("spotify", f"{cc}_weekly", f"/spotify/country/{cc}_weekly.html")
    scrape("spotify", "artists", "/spotify/artists.html")
    scrape("spotify", "listeners", "/spotify/listeners.html")
    scrape("spotify", "listeners_2", "/spotify/listeners2.html")

    scrape("itunes", "artists", "/itunes/")
    scrape("itunes", "artists_extended", "/itunes/extended.html")
    for base in discover_itunes_country_bases():
        cc = base.strip("/").removeprefix("pop") or "us"
        scrape("itunes", f"{cc}_pop", f"{base}full.html")

    scrape("youtube", "realtime", "/youtube/")
    for region in ("anglo", "hispano", "asian", "other"):
        scrape("youtube", f"realtime_{region}", f"/youtube/realtime_{region}.html")
    scrape("youtube", "trending", "/youtube/trending.html")

    scrape("worldwide", "index_full", "/ww/index_full.html")

    scrape("radio", "overall", "/radio/")


if __name__ == "__main__":
    main()
