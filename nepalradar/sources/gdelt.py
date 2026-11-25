"""Coverage of Nepal by the world's press, through the GDELT DOC 2.0 API (free, no key).

GDELT indexes news sites worldwide in 65 languages, from January 2017 to today. It finds what Nepal's own
portals cannot show: Indian, Bangladeshi, Malaysian, Gulf and Western outlets writing about Nepal and Nepali
people abroad. It is used twice:

* fresh:   the last `lookback_hours`, one query per entry in config `sources.gdelt.queries`
* archive: any past day since 2017, one query per day (GDELT returns at most 250 articles per query, so the
           archive walks day by day)

GDELT asks for at most one request every 5 seconds; this module waits 6 s between calls and backs off when
told to slow down. Titles only: GDELT does not return snippets.

GDELT also sheds load: in November 2026 it refused (HTTP 429) about half of all requests whatever their
spacing, and every request from GitHub's shared runners. So the daily run retries patiently, and when GDELT
still refuses, it reuses the articles of the last fetch that worked (data/gdelt_last.json) that are still
inside the time window: one good answer a day keeps the world's coverage of Nepal on the dashboard.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import time
from dataclasses import asdict
from pathlib import Path

from ..http import FetchError, get
from ..models import Article
from ..text import domain
from . import SourceResult

API = "https://api.gdeltproject.org/api/v2/doc/doc"
SPACING = 6.0
BACKOFF = (45, 90, 150, 240)       # seconds to wait after a refusal; GDELT's penalty outlasts short waits
LANG = {"english": "en", "nepali": "ne", "hindi": "hi", "bengali": "bn", "chinese": "zh", "japanese": "ja"}
_last_call = [0.0]


def _wait() -> None:
    gap = time.monotonic() - _last_call[0]
    if gap < SPACING:
        time.sleep(SPACING - gap)


def _done() -> None:
    _last_call[0] = time.monotonic()        # spacing counts from the end of the previous answer


def build_query(query: str, languages: list[str] | None = None) -> str:
    q = query.strip()
    if languages:
        langs = " OR ".join(f"sourcelang:{l}" for l in languages)
        q = f"{q} ({langs})" if len(languages) > 1 else f"{q} sourcelang:{languages[0]}"
    return q


def parse(data: dict, cfg: dict | None = None) -> list[Article]:
    cfg = cfg or {}
    skip = {d.lower().removeprefix("www.") for d in cfg.get("skip_domains", [])}
    weight = float(cfg.get("weight", 0.6))
    out = []
    for a in (data or {}).get("articles") or []:
        url, title = a.get("url") or "", (a.get("title") or "").strip()
        if not url or not title:
            continue
        d = (a.get("domain") or domain(url)).lower().removeprefix("www.")
        if d in skip:
            continue
        try:
            seen = dt.datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
            published = seen.isoformat(timespec="seconds")
        except ValueError:
            published = ""
        country = a.get("sourcecountry") or ""
        out.append(Article(
            source="gdelt", source_id=hashlib.sha1(url.encode()).hexdigest()[:14], outlet=d, title=title, url=url,
            published=published, region="Nepal" if country == "Nepal" else (country or "International"),
            lang=LANG.get((a.get("language") or "").lower(), (a.get("language") or "")[:2].lower()), weight=weight,
        ))
    return out


def query(q: str, *, timespan: str = "", start: dt.datetime | None = None, end: dt.datetime | None = None,
          maxrecords: int = 250, attempts: int = 3) -> dict:
    params = {"query": q, "mode": "artlist", "format": "json", "maxrecords": str(maxrecords), "sort": "datedesc"}
    if timespan:
        params["timespan"] = timespan
    if start:
        params["startdatetime"] = start.strftime("%Y%m%d%H%M%S")
    if end:
        params["enddatetime"] = end.strftime("%Y%m%d%H%M%S")
    url = API + "?" + "&".join(f"{k}={requests_quote(v)}" for k, v in params.items())
    last = ""
    for attempt in range(attempts):
        _wait()
        try:
            body = get(url, as_json=False, tries=1, timeout=(10, 90))
            _done()
        except FetchError as e:
            _done()
            last = str(e).split(" for http")[0]          # "HTTP 429", "ReadTimeout": the URL adds nothing
            if attempt < attempts - 1:
                time.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)] + random.uniform(0, 15))
            continue
        if body is None:
            return {}
        body = body.strip()
        if body.startswith("{"):
            import json
            try:
                return json.loads(body)
            except ValueError:
                return {}
        if "limit requests" in body.lower():           # "Please limit requests to one every 5 seconds"
            # After a breach GDELT keeps refusing for a while, and every early retry restarts the clock.
            last = "rate limited"
            if attempt < attempts - 1:
                time.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)] + random.uniform(0, 15))
            continue
        return {}                                       # GDELT answers "no results" with an empty page
    raise FetchError(f"GDELT: {last}")


def requests_quote(v: str) -> str:
    from urllib.parse import quote
    return quote(v, safe="")


def fetch_window(cfg: dict, q: str, start: dt.datetime, end: dt.datetime, min_span: dt.timedelta) -> list[Article]:
    """Everything GDELT has for one query between start and end. GDELT returns at most 250 articles per query,
    so a window that comes back full is split in half until the pieces fit (or reach min_span)."""
    out: dict[str, Article] = {}
    windows = [(start, end)]
    while windows:
        a, b = windows.pop()
        data = query(q, start=a, end=b)
        if len((data or {}).get("articles") or []) >= 250 and b - a > min_span:
            mid = a + (b - a) / 2
            windows += [(a, mid), (mid, b)]
            continue
        for x in parse(data, cfg):
            out.setdefault(x.url, x)
    return list(out.values())


def save_last(path: Path, articles: list[Article], now: dt.datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched_at": now.isoformat(timespec="seconds"), "articles": [asdict(a) for a in articles]},
                               ensure_ascii=False, indent=0), encoding="utf-8")


def load_last(path: Path, since: dt.datetime) -> tuple[list[Article], str]:
    """The last good fetch's articles that are still inside the window, and when it was made."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], ""
    keep = [Article(**a) for a in d.get("articles", []) if a.get("published", "") >= since.isoformat(timespec="seconds")]
    return keep, d.get("fetched_at", "")


def fetch(cfg: dict, lookback_hours: int = 48, now: dt.datetime | None = None, last_path: Path | None = None) -> SourceResult:
    """Fresh coverage for the daily run: the last lookback_hours, in pieces of at least 6 hours."""
    res = SourceResult("gdelt")
    queries = cfg.get("queries") or ["nepal"]
    end = (now or dt.datetime.now(dt.timezone.utc)).replace(microsecond=0)
    start = end - dt.timedelta(hours=min(int(lookback_hours), 24 * 7))
    found: dict[str, Article] = {}
    failed = []
    capped = False
    for q in queries:
        qq = build_query(q, cfg.get("languages"))
        try:
            # "The last N hours" is GDELT's fast path. Only when that answer is full (250) is the window split
            # into dated pieces, which GDELT answers more slowly; if those fail, the first answer is kept.
            data = query(qq, timespan=f"{int((end - start).total_seconds() // 3600)}h", attempts=cfg.get("attempts", 4))
        except FetchError as e:
            failed.append(f"{q[:40]} ({e})")
            continue
        for a in parse(data, cfg):
            found.setdefault(a.url, a)
        if len((data or {}).get("articles") or []) >= 250:
            try:
                for a in fetch_window(cfg, qq, start, end, dt.timedelta(hours=6)):
                    found.setdefault(a.url, a)
            except FetchError:
                capped = True
    res.articles = list(found.values())
    res.detail = f"{len(res.articles)} articles from {len({a.outlet for a in res.articles})} sites"
    if capped:
        res.detail += " (newest 250 only: GDELT did not answer the narrower queries)"
    if failed:
        res.detail += "; failed: " + "; ".join(failed)
    if last_path and res.articles and not failed:
        save_last(last_path, res.articles, end)
    if failed and len(failed) == len(queries):
        old, when = load_last(last_path, start) if last_path else ([], "")
        if old:
            # Still flagged (the digest lists it under source problems), but the dashboard keeps the coverage.
            res.articles = old
            res.detail = (f"GDELT refused this run; reusing {len(old)} articles from the fetch of {when[:16].replace('T', ' ')} UTC"
                          f" (failed: {'; '.join(failed)})")
        else:
            res.ok, res.error = False, "every GDELT query failed: " + "; ".join(failed)
    return res


def fetch_day(cfg: dict, day: dt.date, extra_query: str = "") -> list[Article]:
    """Archive: everything GDELT has about Nepal for one UTC day (busy days are split down to 3-hour pieces)."""
    out: dict[str, Article] = {}
    queries = cfg.get("queries") or ["nepal"]
    start = dt.datetime.combine(day, dt.time(0), dt.timezone.utc)
    for q in queries:
        qq = build_query(f"{q} {extra_query}".strip(), cfg.get("languages"))
        for a in fetch_window(cfg, qq, start, start + dt.timedelta(days=1), dt.timedelta(hours=3)):
            out.setdefault(a.url, a)
    return list(out.values())
