"""Past articles from Nepali news sites that run WordPress, through their public REST API.

Onlinekhabar, Khabarhub (Nepali and English editions) and News of Nepal publish every article through
/wp-json/wp/v2/posts, which can be asked for any date range. That gives a complete archive of what those
sites published on any past day, going back to their first post, not just what a search engine kept.

Requests are paged 100 at a time with a pause between pages. Sites that switch the API off or put it behind a
bot check (Desh Sanchar, Nepal Press) are reported and skipped.
"""
from __future__ import annotations

import datetime as dt
import time

from ..http import FetchError, get
from ..models import Article
from ..text import strip_html
from . import SourceResult

FIELDS = "id,date_gmt,link,title,excerpt"
PAUSE = 0.6


def parse(posts: list, site: dict) -> list[Article]:
    out = []
    for p in posts or []:
        title = strip_html(((p.get("title") or {}).get("rendered")) or "")
        link = p.get("link") or ""
        if not title or not link:
            continue
        d = p.get("date_gmt") or ""
        published = f"{d}+00:00" if d and "+" not in d and not d.endswith("Z") else d.replace("Z", "+00:00")
        out.append(Article(
            source="wordpress", source_id=f"{site['name']}:{p.get('id')}", outlet=site["name"], title=title, url=link,
            published=published, summary=strip_html(((p.get("excerpt") or {}).get("rendered")) or "")[:600],
            region=site.get("region", "Nepal"), lang=site.get("lang", "ne"), weight=float(site.get("weight", 0.8)),
        ))
    return out


def fetch_range(site: dict, start: dt.datetime, end: dt.datetime, search: str = "", max_pages: int = 200) -> list[Article]:
    """Every post the site published between start and end (UTC)."""
    base = site["base"].rstrip("/")
    out: list[Article] = []
    for page in range(1, max_pages + 1):
        url = (f"{base}/wp-json/wp/v2/posts?after={start.strftime('%Y-%m-%dT%H:%M:%S')}"
               f"&before={end.strftime('%Y-%m-%dT%H:%M:%S')}&per_page=100&page={page}&orderby=date&order=asc"
               f"&_fields={FIELDS}")
        if search:
            from urllib.parse import quote
            url += f"&search={quote(search)}"
        try:
            posts = get(url)
        except FetchError as e:
            if "HTTP 400" in str(e) and page > 1:      # asked past the last page
                break
            raise
        if not posts:
            break
        out += parse(posts, site)
        if len(posts) < 100:
            break
        time.sleep(PAUSE)
    return out


def fetch_day(sites: list[dict], day: dt.date, search: str = "") -> SourceResult:
    res = SourceResult("wordpress")
    start = dt.datetime.combine(day, dt.time(0))
    failed = []
    for site in sites:
        if site.get("enabled") is False:
            continue
        try:
            res.articles += fetch_range(site, start, start + dt.timedelta(days=1), search)
        except FetchError as e:
            failed.append(f"{site['name']} ({e})")
        time.sleep(PAUSE)
    res.detail = f"{len(res.articles)} posts"
    if failed:
        res.detail += "; failed: " + "; ".join(failed)
        if len(failed) == len(sites):
            res.ok, res.error = False, "every site failed"
    return res
