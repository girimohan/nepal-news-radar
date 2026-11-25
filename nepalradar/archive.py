"""The archive: every Nepal-related article the radar has seen or back-filled, one file per day.

    docs/archive/2026/11/25.jsonl     one article per line (id, date, outlet, title, link, snippet, lang, source)
    docs/archive/index.json           article counts per day, outlet and language, for the dashboard

One small file per day keeps git diffs small (a day's file only changes while that day is inside the daily
run's window) and lets the dashboard on GitHub Pages load just the days a search asks for.

It is filled in two ways:
* every daily run adds the articles it collected (so the archive grows by itself from the first run on), and
* `python -m nepalradar archive backfill --from 2025-01-01 --to 2025-03-31` fetches past days from GDELT
  (world press, since 2017) and the WordPress sites' own archives (complete, back to their first post).
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path

from .models import Article
from .text import canonical_url, has_keyword

SNIPPET = 220


def day_path(root: Path, day: str) -> Path:
    y, m, d = day[:10].split("-")
    return root / y / m / f"{d}.jsonl"


def record(a: Article) -> dict:
    return {"id": canonical_url(a.url), "published": a.published, "outlet": a.outlet, "title": a.title, "url": a.url,
            "summary": (a.summary or "")[:SNIPPET], "lang": a.lang, "region": a.region, "source": a.source}


def read_day(root: Path, day: str) -> list[dict]:
    p = day_path(root, day)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def add(root: Path, articles: list[Article]) -> dict[str, int]:
    """Store articles by their publication day (UTC), skipping links already stored. Returns new per day."""
    by_day: dict[str, list[Article]] = {}
    for a in articles:
        if a.published and a.source not in ("hackernews", "reddit"):
            by_day.setdefault(a.published[:10], []).append(a)
    added: dict[str, int] = {}
    for day, arts in sorted(by_day.items()):
        rows = read_day(root, day)
        have = {r["id"] for r in rows}
        new = 0
        for a in arts:
            r = record(a)
            if r["id"] not in have:
                have.add(r["id"])
                rows.append(r)
                new += 1
        if new:
            rows.sort(key=lambda r: (r["published"], r["outlet"], r["title"]))
            p = day_path(root, day)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            added[day] = new
    if added:
        update_index(root, list(added))
    return added


def update_index(root: Path, days: list[str] | None = None) -> dict:
    """Recount the given days (or every day when None) into index.json."""
    ip = root / "index.json"
    idx = {"days": {}}
    if ip.exists():
        try:
            idx = json.loads(ip.read_text(encoding="utf-8"))
        except ValueError:
            idx = {"days": {}}
    if days is None:
        days = sorted(f"{p.parent.parent.name}-{p.parent.name}-{p.stem}" for p in root.glob("*/*/*.jsonl"))
    for day in days:
        rows = read_day(root, day)
        if rows:
            idx["days"][day] = {"n": len(rows), "langs": dict(Counter(r.get("lang") or "?" for r in rows)),
                                "sources": dict(Counter(r.get("source") or "?" for r in rows))}
        else:
            idx["days"].pop(day, None)
    ds = sorted(idx["days"])
    idx.update(first=ds[0] if ds else "", last=ds[-1] if ds else "", total=sum(v["n"] for v in idx["days"].values()),
               updated=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    root.mkdir(parents=True, exist_ok=True)
    ip.write_text(json.dumps(idx, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    return idx


def daterange(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def search(root: Path, words: list[str], start: dt.date, end: dt.date, outlet: str = "", lang: str = "",
           match: str = "any") -> list[dict]:
    """Articles between start and end whose headline or snippet contains the words (any or all of them).
    Nepali words match with their joined postpositions (भूकम्प finds भूकम्पको, भूकम्पमा)."""
    words = [w.lower() for w in words if w.strip()]
    out = []
    for d in daterange(start, end):
        for r in read_day(root, d.isoformat()):
            if outlet and outlet.lower() not in r["outlet"].lower():
                continue
            if lang and r.get("lang") != lang:
                continue
            if words:
                text = f"{r['title']} {r.get('summary', '')}".lower()
                hits = [has_keyword(text, w) for w in words]
                if not (all(hits) if match == "all" else any(hits)):
                    continue
            out.append(r)
    out.sort(key=lambda r: r["published"], reverse=True)
    return out


def backfill(root: Path, cfg: dict, start: dt.date, end: dt.date, sources: set[str], query: str = "",
             log=print) -> int:
    """Fetch past days from GDELT and the WordPress sites and add them to the archive. Safe to re-run: links
    already stored are skipped, so an interrupted backfill can simply be started again."""
    from .pipeline import nepal_relevant
    from .sources import gdelt, wordpress
    arch = cfg.get("archive", {})
    total = 0
    for day in daterange(start, end):
        got: list[Article] = []
        notes = []
        if "wordpress" in sources:
            r = wordpress.fetch_day(arch.get("wordpress", []), day, search=query)
            got += r.articles
            notes.append(f"wordpress {len(r.articles)}" + (f" ({r.detail.split('; ', 1)[1]})" if "failed" in r.detail else ""))
        if "gdelt" in sources:
            if day < dt.date(2017, 1, 1):
                notes.append("gdelt: starts 2017-01-01")
            else:
                try:
                    g = gdelt.fetch_day(cfg.get("sources", {}).get("gdelt", {}), day, extra_query=query)
                    got += g
                    notes.append(f"gdelt {len(g)}")
                except Exception as e:  # keep going: one bad day should not stop a long backfill
                    notes.append(f"gdelt failed ({type(e).__name__}: {str(e)[:60]})")
        got = [a for a in got if nepal_relevant(a, cfg)]
        n = sum(add(root, got).values())
        total += n
        log(f"{day}: {n} new  [{', '.join(notes)}]")
    update_index(root)
    return total
