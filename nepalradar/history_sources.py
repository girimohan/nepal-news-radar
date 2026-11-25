"""Historic Nepal news beyond Wikipedia articles, for "On this day" and the daily briefings.

- **Wikipedia's daily news pages** ("Portal:Current events/2015 September 20", from about 2002): every line
  is dated by the page and cites a report.
- **nepalnews.com, 2001-2004**, Nepal's first news portal, as saved by the Internet Archive's Wayback
  Machine: its daily pages of news ("Kathmandu, May 25: ...").
- **Nepali Times archive** (archive.nepalitimes.com, every weekly issue since #1 of 19 July 2000).
- **Kantipur Archive** (ekantipur.com/Kantipur-Archive): Kantipur reprints one of its own stories from about
  26 years ago each day.
- **Daily briefings**: round-ups of the day's news that Nepali outlets publish (Nepal News Evening Briefing,
  Onlinekhabar's Daily Digest).
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from .http import USER_AGENT

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
_local = threading.local()


def _session() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers["User-Agent"] = USER_AGENT + " on-this-day"
    return _local.s


def get(url: str, params: dict | None = None, timeout: float = 40, tries: int = 3, pause: float = 0) -> str:
    """Text of a page, or "" when it cannot be had (404, or still failing after retries)."""
    for attempt in range(tries):
        try:
            if pause:
                time.sleep(pause)
            r = _session().get(url, params=params, timeout=(8, timeout))
            if r.status_code == 404:
                return ""
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(4 * (attempt + 1))
                continue
            r.encoding = r.encoding or "utf-8"
            return r.text if r.ok else ""
        except requests.RequestException:
            time.sleep(3 * (attempt + 1))
    return ""


def strip_tags(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def slug_title(url: str) -> str:
    """A readable title from an article link: .../nepal-adopts-new-constitution.html -> "Nepal adopts new constitution"."""
    seg = urlparse(url).path.rstrip("/").split("/")[-1] if url else ""
    seg = re.sub(r"\.(s?html?|php|aspx?|cms|stm|ece)$", "", seg, flags=re.I)
    words = [w for w in re.split(r"[-_+]+", seg)
             if w and not re.fullmatch(r"[0-9a-f]{6,}|\d{5,}|index|article\d*|story|news", w, re.I)]
    if len(words) < 3:
        return ""
    s = " ".join(words)
    return s[:1].upper() + s[1:]


def domain(url: str) -> str:
    return re.sub(r"^www\.", "", urlparse(url or "").netloc)


# ------------------------------------------------------------------ Wikipedia's daily news pages
_LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
_EXT = re.compile(r"\[(https?://[^\s\]]+)(?:\s+([^\]]*))?\]")
_TOPIC = re.compile(r"^(?:\s*\[\[[^\]]+\]\]\s*[,;/]?\s*)+$")
GENERIC_TOPICS = {"nepal", "kathmandu", "india", "china", "politics of nepal", "government of nepal", "economy of nepal"}


def _clean(s: str) -> str:
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = _EXT.sub("", s)
    s = _LINK.sub(lambda m: m.group(2) or m.group(1), s)
    s = re.sub(r"'{2,}", "", s)
    s = htmllib.unescape(s).replace(" ", " ")
    s = re.sub(r"\s+([.,;])", r"\1", re.sub(r"\s+", " ", s))
    return re.sub(r"\.(\s*\.)+", ".", s).strip(" *:-–")


def current_events_items(wikitext: str, day: dt.date, nepal_re: re.Pattern) -> list[dict]:
    """Nepal lines of a "Portal:Current events/<date>" page, each with its topic article and cited report."""
    out, topics = [], {}
    for raw in (wikitext or "").splitlines():
        m = re.match(r"^(\*+)\s*(.*)$", raw.strip())
        if not m:
            continue
        depth, body = len(m.group(1)), m.group(2).strip()
        for k in [k for k in topics if k >= depth]:
            del topics[k]
        if _TOPIC.match(body):
            topics[depth] = _LINK.search(body).group(1).strip()
            continue
        text = _clean(body)
        if len(text) < 25:
            continue
        context = [topics[k] for k in sorted(topics)]
        if not nepal_re.search(text) and not any(nepal_re.search(t) for t in context):
            continue
        # The article this line is about: its nearest Nepal topic, else its nearest topic, else its first link.
        nep = [t for t in context if nepal_re.search(t) and t.lower() not in GENERIC_TOPICS]
        first = _LINK.search(body)
        links = [l.group(1).strip() for l in _LINK.finditer(body)]
        nep_links = [l for l in links if nepal_re.search(l) and l.lower() not in GENERIC_TOPICS]
        title = (nep[-1] if nep else nep_links[0] if nep_links else context[-1] if context else links[0] if links else "")
        news = None
        ext = _EXT.search(body)
        if ext:
            url, label = ext.group(1), (ext.group(2) or "").strip(" ()")
            outlet = _clean(label) or domain(url)
            news = {"title": slug_title(url) or f"{outlet} report", "url": url, "outlet": outlet,
                    "date": day.isoformat(), "kind": "current_events"}
        if not text.endswith((".", "!", "?")):
            text += "."
        out.append({"title": title, "sentence": text, "news": news})
    return out


def current_events(wiki_call, day: dt.date, nepal_re: re.Pattern) -> list[dict]:
    page = f"Portal:Current events/{day.year} {MONTHS[day.month - 1]} {day.day}"
    d = wiki_call({"action": "parse", "page": page, "prop": "wikitext", "redirects": 1})
    return current_events_items((d.get("parse") or {}).get("wikitext", ""), day, nepal_re)


# ------------------------------------------------------------------ nepalnews.com 2001-2004 (Wayback Machine)
CDX = "https://web.archive.org/cdx/search/cdx"
_MON3 = {m[:3].lower(): i + 1 for i, m in enumerate(MONTHS)}
_DATELINE = re.compile(r"<b>\s*([A-Z][A-Za-z .'-]{2,30}?),\s*([A-Z][a-z]{2,8})\.?\s*(\d{1,2})\s*:?\s*</b>")
_SIGNATURE = re.compile(r"nepalnews\.com\s+\w{1,3}\s+([A-Z][a-z]{2,8})\.?\s*(\d{1,2})\b")   # "nepalnews.com am Jan 2"


def wayback_index(year: int, cache_dir: Path | None) -> list[list[str]]:
    """[timestamp, url] of the saved nepalnews.com.np/archive/<year>/ pages (cached for good: the past is fixed)."""
    path = cache_dir / "_wayback" / f"nepalnews-{year}.json" if cache_dir else None
    if path and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    text = get(CDX, {"url": f"nepalnews.com.np/archive/{year}/*", "filter": ["statuscode:200", "original:.*\\.htm$"],
                     "fl": "timestamp,original", "collapse": "urlkey", "limit": 5000, "output": "json"}, timeout=90)
    if not text:
        return []
    try:
        rows = [r for r in json.loads(text)[1:] if len(r) == 2]
    except ValueError:
        return []
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def month_pages(rows: list[list[str]], month: int) -> list[tuple[int, int | None, str, str]]:
    """The month's daily pages in order: (order key, day if the file name gives it, timestamp, url)."""
    names = {MONTHS[month - 1].lower(), MONTHS[month - 1][:3].lower(), "sept" if month == 9 else "-"}
    out = []
    for ts, url in rows:
        m = re.search(r"/archive/\d{4}/([a-z]+)/(arc[^/]*)\.htm$", url, re.I)
        if not m:
            continue
        folder, name = m.group(1).lower(), m.group(2).lower()
        f = re.match(r"arc_([a-z]+)\d\d_(\d+)$", name)                    # 2004: arc_june04_12
        if f:
            if f.group(1)[:3] != MONTHS[month - 1][:3].lower():
                continue
            out.append((int(f.group(2)), int(f.group(2)), ts, url))
            continue
        n = re.match(r"arc(\d+)$", name)                                    # 2001-2003: arc222
        if n and folder in names:
            out.append((int(n.group(1)), None, ts, url))
    return sorted(out)


def parse_nepalnews(html: str, year: int, default: dt.date | None = None) -> list[dict]:
    """Stories of a nepalnews.com daily page: headline, date and first lines. The date comes from the
    dateline ("Kathmandu, May 25:", 2001), the sign-off ("nepalnews.com am Jan 2", 2002-2003) or, for 2004,
    whose stories carry neither, from the page's file name (`default`)."""
    h = re.sub(r"\s+", " ", html or "")
    out = []
    for chunk in re.split(r"<a name=\"?\w+\"?>", h, flags=re.I)[1:]:
        chunk = re.split(r"<hr\b", chunk, maxsplit=1, flags=re.I)[0]
        head = strip_tags(chunk.split("</a>", 1)[0])
        if not head or len(head) < 8:
            continue
        rest = chunk.split("</a>", 1)[1] if "</a>" in chunk else ""
        when, place = None, ""
        m = _DATELINE.search(chunk)
        sig = _SIGNATURE.search(chunk)
        if m:
            mon, d, place = _MON3.get(m.group(2)[:3].lower()), m.group(3), m.group(1).strip()
        elif sig:
            mon, d = _MON3.get(sig.group(1)[:3].lower()), sig.group(2)
        else:
            mon, d = None, None
        if mon:
            try:
                when = dt.date(year, mon, int(d))
            except ValueError:
                when = None
        when = when or default
        if not when:
            continue
        body = strip_tags(_DATELINE.sub(" ", rest, count=1))
        body = _SIGNATURE.sub("", body).strip()[:400]
        out.append({"title": head, "place": place, "date": when, "text": body})
    return out


def nepalnews_day(day: dt.date, cache_dir: Path | None = None, max_fetches: int = 7) -> list[dict]:
    """The stories nepalnews.com dated `day`, found by a binary search over the month's saved pages."""
    pages = month_pages(wayback_index(day.year, cache_dir), day.month)
    if not pages:
        return []

    def fetch(i):
        _, named_day, ts, url = pages[i]
        default = dt.date(day.year, day.month, named_day) if named_day else None
        stories = parse_nepalnews(get(f"https://web.archive.org/web/{ts}id_/{url}", timeout=60, pause=0.5), day.year, default)
        for s in stories:
            s["url"] = f"https://web.archive.org/web/{ts}/{url}"
        return stories

    named = [i for i, p in enumerate(pages) if p[1] == day.day]
    if named:
        return [s for s in fetch(named[0]) if s["date"] == day]
    lo, hi = 0, len(pages) - 1
    for _ in range(max_fetches):
        if lo > hi:
            break
        mid = (lo + hi) // 2
        stories = fetch(mid)
        hits = [s for s in stories if s["date"] == day]
        if hits:
            return hits
        dates = [s["date"] for s in stories]
        if not dates:                                   # an index or picture page: step past it
            lo = mid + 1
        elif max(dates) < day:
            lo = mid + 1
        else:
            hi = mid - 1
    return []


# ------------------------------------------------------------------ Nepali Times archive (weekly, since 2000)
NT = "https://archive.nepalitimes.com"
NT_FIRST = dt.date(2000, 7, 19)
_NT_SKIP = re.compile(r"^/(issue|archive|search|about-town|follow|epaper|category|tag|author|page|multimedia|"
                      r"about$|reach$|article$|contact|privacy|terms|advertise|subscribe|newsletter|"
                      r"news$|editorial$|opinion$|climate$|reviews$|economy$|$)")


def parse_nt_issue(html: str) -> dict | None:
    m = re.search(r"Published on\s*(?:<[^>]+>\s*)*([A-Z][a-z]{2,8} \d{1,2}, \d{4})", html or "")
    if not m:
        return None
    try:
        published = dt.datetime.strptime(m.group(1), "%b %d, %Y").date()
    except ValueError:
        try:
            published = dt.datetime.strptime(m.group(1), "%B %d, %Y").date()
        except ValueError:
            return None
    arts: dict[str, dict] = {}
    for href, inner in re.findall(r'<a[^>]*href="(/[^"#?]*)"[^>]*>(.*?)</a>', html, re.S):
        if _NT_SKIP.match(href):
            continue
        text = strip_tags(inner)
        if not text:
            continue
        a = arts.setdefault(href, {"url": NT + href, "title": "", "dek": ""})
        if not a["title"]:
            a["title"] = text
        elif not a["dek"] and text != a["title"]:
            a["dek"] = text
    # The page's structured data gives each article's description: a better teaser than the link text.
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for part in (data.get("hasPart") or []) if isinstance(data, dict) else []:
            path = urlparse(part.get("url", "")).path
            if path in arts and part.get("description") and not arts[path]["dek"]:
                arts[path]["dek"] = htmllib.unescape(part["description"]).strip()
    arts_l = [a for a in arts.values() if len(a["title"]) > 3 and not a["title"].startswith("Add us")]
    return {"published": published, "articles": arts_l}


class NepaliTimes:
    """Finds the weekly issue for a date by searching issue numbers, remembering each issue's date."""

    def __init__(self, cache_dir: Path | None = None):
        self.lock = threading.Lock()
        self.path = cache_dir / "_nepalitimes_issues.json" if cache_dir else None
        self.dates: dict[int, str] = {}
        if self.path and self.path.exists():
            self.dates = {int(k): v for k, v in json.loads(self.path.read_text(encoding="utf-8")).items()}
        self.pages: dict[int, dict | None] = {}
        self._latest: int | None = None

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock:
                self.path.write_text(json.dumps(dict(sorted(self.dates.items()))), encoding="utf-8")

    def latest(self) -> int:
        if self._latest is None:
            nums = [int(x) for x in re.findall(r"Issue #(\d+)", get(f"{NT}/archive"))]
            self._latest = max(nums) if nums else max(self.dates or {1300: ""})
        return self._latest

    def issue(self, n: int) -> dict | None:
        with self.lock:
            if n in self.pages:
                return self.pages[n]
        page = parse_nt_issue(get(f"{NT}/issue/{n}"))
        if page:
            page["number"], page["url"] = n, f"{NT}/issue/{n}"
        with self.lock:
            self.pages[n] = page
            if page:
                self.dates[n] = page["published"].isoformat()
        return page

    def date_of(self, n: int) -> dt.date | None:
        if n in self.dates:
            return dt.date.fromisoformat(self.dates[n])
        p = self.issue(n)
        return p["published"] if p else None

    def for_day(self, day: dt.date, max_fetches: int = 14) -> dict | None:
        """The first issue published on or after `day`, if within a week (it reports that week's news)."""
        if day < NT_FIRST - dt.timedelta(days=6):
            return None
        lo, hi = 1, self.latest()
        for _ in range(max_fetches):
            if lo >= hi:
                break
            # Interpolate between the nearest issues with known dates (issues are about weekly).
            with self.lock:
                pairs = list(self.dates.items())
            known = sorted((n, dt.date.fromisoformat(d)) for n, d in pairs if lo <= n <= hi)
            below = [k for k in known if k[1] < day]
            above = [k for k in known if k[1] >= day]
            if below:
                lo = max(lo, below[-1][0] + 1)
            if above:
                hi = min(hi, above[0][0])
            if lo >= hi:
                break
            n0, d0 = below[-1] if below else (1, NT_FIRST)
            n1, d1 = above[0] if above else (hi, d0 + dt.timedelta(weeks=hi - n0))
            span = max((d1 - d0).days, 1)
            guess = n0 + round((n1 - n0) * (day - d0).days / span)
            guess = min(max(guess, lo), hi - 1) if hi > lo else lo
            d = self.date_of(guess)
            if d is None:                               # a missing issue number: drop it from the range
                if guess == lo:
                    lo += 1
                else:
                    hi = guess
                continue
            if d < day:
                lo = guess + 1
            else:
                hi = guess
        d = self.date_of(hi)
        if d is None or not (day <= d <= day + dt.timedelta(days=7)):
            return None
        return self.issue(hi)


# ------------------------------------------------------------------ Kantipur Archive
KA = "https://ekantipur.com/Kantipur-Archive"
_NE_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def _meta(html: str, name: str) -> str:
    m = re.search(rf'<meta[^>]+(?:property|name)="{name}"[^>]+content="([^"]*)"', html) or \
        re.search(rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{name}"', html)
    return htmllib.unescape(m.group(1)).strip() if m else ""


def _title(html: str) -> str:
    t = _meta(html, "og:title") or strip_tags((re.search(r"<title>(.*?)</title>", html or "", re.S) or [None, ""])[1])
    return re.sub(r"\s*[-|]\s*(कान्तिपुर|Kantipur|ekantipur).*$", "", t).strip()


def years_ago(*texts: str) -> int | None:
    for t in texts:
        m = re.search(r"(\d+)\s+years?\s+ago", t or "", re.I) or re.search(r"(\d+)\s*वर्ष\s*(?:अघि|अगाडि|पहिले)",
                                                                          (t or "").translate(_NE_DIGITS))
        if m:
            return int(m.group(1))
    return None


def bs_years_ago(text: str) -> int | None:
    """How old the reprinted story is, from its Bikram Sambat years: the reprint is dated in the current BS
    year ("मंसिर ८, २०८३") and the story names its own ("८ असोज २०५७")."""
    years = [int(y) for y in re.findall(r"(?<!\d)(20[0-9]{2})(?!\d)", (text or "").translate(_NE_DIGITS)) if 2000 <= int(y) <= 2100]
    if not years:
        return None
    now = max(years)
    old = [y for y in years if y < now]
    if not old:
        return None
    common = max(set(old), key=old.count)
    return now - common if 0 < now - common < 80 else None


def kantipur_pick(day: dt.date) -> dict | None:
    """Kantipur's archive story for `day` (it reprints one a day; the listing holds about the last month)."""
    index = get(KA)
    stamp = f"/Kantipur-Archive/{day.year}/{day.month:02d}/{day.day:02d}/"
    links = list(dict.fromkeys(re.findall(rf'href="((?:https://ekantipur\.com)?{re.escape(stamp)}[^"]+)"', index)))
    links = [l if l.startswith("http") else "https://ekantipur.com" + l for l in links]
    ne = [l for l in links if "/en/" not in l]
    if not ne and not links:
        return None
    url = (ne or links)[0]
    page = get(url)
    if not page:
        return None
    en_url = next((l for l in links if "/en/" in l), "")
    if not en_url:
        m = re.search(rf'href="((?:https://ekantipur\.com)?{re.escape(stamp)}en/[^"]+)"', page)
        en_url = ("https://ekantipur.com" + m.group(1) if m and m.group(1).startswith("/") else m.group(1)) if m else ""
    en = get(en_url) if en_url else ""
    title, summary = _title(page), _meta(page, "og:description") or _meta(page, "description")
    title_en = _title(en) if en else ""
    summary_en = (_meta(en, "og:description") or _meta(en, "description")) if en else ""
    body = strip_tags(page)
    ago = years_ago(title_en, summary_en, title, summary, strip_tags(en)[:3000], body[:3000]) or bs_years_ago(body)
    return {"date": day.isoformat(), "title": title, "summary": summary, "url": url, "title_en": title_en,
            "summary_en": summary_en, "url_en": en_url, "years_ago": ago, "year": day.year - ago if ago else None}


# ------------------------------------------------------------------ daily briefings
def latest_briefings(cfg: dict, now: dt.datetime | None = None, max_age_days: int = 3) -> list[dict]:
    """The newest edition of each configured round-up (a WordPress search on the outlet's own site)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for b in cfg.get("briefings", []):
        text = get(b["base"].rstrip("/") + "/wp-json/wp/v2/posts",
                   {"search": b["search"], "per_page": 5, "_fields": "date_gmt,link,title,excerpt"}, timeout=30)
        try:
            posts = json.loads(text) if text else []
        except ValueError:
            posts = []
        want = b["search"].lower()
        for p in posts:
            title = strip_tags(p.get("title", {}).get("rendered", ""))
            if want not in title.lower():
                continue
            when = dt.datetime.fromisoformat(p["date_gmt"]).replace(tzinfo=dt.timezone.utc)
            if (now - when).days > max_age_days:
                break
            out.append({"name": b["name"], "title": title, "url": p["link"], "published": when.isoformat(),
                        "excerpt": strip_tags(p.get("excerpt", {}).get("rendered", ""))[:300]})
            break
    return out
