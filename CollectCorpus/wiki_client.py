"""Shared Wikipedia client.

Uses `wikipedia-api` (maintained) instead of `wikipedia` (unmaintained since 2014:
returns no sections, and its default User-Agent is rate-limited by Wikimedia with HTTP 429).
For things `wikipedia-api` doesn't cover (revision ids, coordinates, the raw text) we call the MediaWiki API directly.
"""
import threading
import time

import requests
import wikipediaapi

USER_AGENT = "GeoAI-WikiCorpus/0.1 (student course project)"
BATCH = 50  # max titles per MediaWiki API request
MIN_INTERVAL = 0.25  # seconds between our direct API requests, to stay under Wikipedia's rate limit

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT
_throttle_lock = threading.Lock()
_last_request = 0.0


def client(lang="en"):
    return wikipediaapi.Wikipedia(user_agent=USER_AGENT, language=lang)


def _throttle():
    """Keep at least MIN_INTERVAL seconds between our API requests, across threads."""
    global _last_request
    with _throttle_lock:
        wait = _last_request + MIN_INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.time()


def api(lang="en", retries=8, **params):
    """Direct call to the MediaWiki API. Waits and retries when rate-limited (HTTP 429)."""
    params = {"action": "query", "format": "json", "formatversion": 2, **params}
    for attempt in range(retries):
        _throttle()
        try:
            r = session.get(f"https://{lang}.wikipedia.org/w/api.php", params=params, timeout=30)
        except requests.ConnectionError:  # Wikipedia sometimes drops the connection under load
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code != 429 or attempt == retries - 1:
            r.raise_for_status()
            return r.json()
        # Retry-After is the server's minimum; back off further on repeated refusals
        time.sleep(max(int(r.headers.get("Retry-After", 0)), 5) * (attempt + 1))


def flatten_sections(sections, path=()):
    """Turn the section tree into a flat list: [{"path": "History > Kievan Rus'", "text": ...}]."""
    out = []
    for s in sections:
        p = (*path, s.title)
        if s.text.strip():
            out.append({"path": " > ".join(p), "level": len(p), "text": s.text})
        out += flatten_sections(s.sections, p)
    return out


def raw_content(title, lang="en"):
    """The page text exactly as Wikipedia returns it: headings as "== X ==", empty sections kept.
    This is the format of the team's examples/DATA.json (the old `wikipedia` library's page.content),
    which `wikipedia-api` can't reproduce because it splits the text into sections."""
    data = api(lang, prop="extracts", explaintext=1, titles=title, redirects=1)
    pages = data["query"]["pages"]
    return pages[0].get("extract", "") if pages else ""


def page_meta(titles, lang="en"):
    """Current version info for many pages, 50 per request.

    Returns {requested_title: meta | None}. None = page doesn't exist (deleted / never existed).
    meta = {"title", "pageid", "revid", "last_edited", "coordinates"}; "title" is the canonical
    title after normalization and redirects, so if it differs from the requested one the page was renamed.
    """
    out = {}
    for i in range(0, len(titles), BATCH):
        batch = titles[i:i + BATCH]
        params = {"prop": "info|revisions|coordinates", "rvprop": "ids|timestamp",
                  "colimit": "max", "redirects": 1, "titles": "|".join(batch)}
        renamed, pages, cont = {}, {}, {}
        while True:  # the API may split the answer into several "continue" parts
            data = api(lang, **params, **cont)
            q = data.get("query", {})
            for r in q.get("normalized", []) + q.get("redirects", []):
                renamed[r["from"]] = r["to"]
            for p in q.get("pages", []):
                m = pages.setdefault(p["title"], {"title": p["title"], "coordinates": None})
                if p.get("missing") or p.get("invalid"):
                    m["missing"] = True
                    continue
                m["pageid"] = p["pageid"]
                if p.get("revisions"):
                    m["revid"] = p["revisions"][0]["revid"]
                    m["last_edited"] = p["revisions"][0]["timestamp"]
                if p.get("coordinates"):
                    c = p["coordinates"][0]
                    m["coordinates"] = {"lat": c["lat"], "lon": c["lon"]}
            if "continue" not in data:
                break
            cont = data["continue"]
        for t in batch:
            final = t
            while final in renamed:  # normalized -> redirect target
                final = renamed[final]
            m = pages.get(final)
            out[t] = None if m is None or m.get("missing") else m
    return out

