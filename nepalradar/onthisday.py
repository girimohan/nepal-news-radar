"""On this day in Nepal: for today's date, the best-known Nepal event of every past year, and a news piece
from that day about it.

Where it comes from
-------------------
1. **Which incidents happened on this date.** English Wikipedia is searched for the exact date in both
   spellings ("25 November 1990", "November 25, 1990") together with "Nepal", and the curated "<year> in
   Nepal" pages are read for lines with that date. A hit counts only when the date appears in a sentence of
   the article's prose (not in a reference) and either that sentence or the article is about Nepal.
2. **Which one is the most famous.** The number of Wikipedia language editions that have an article on it
   (its Wikidata sitelinks). The 2015 earthquake has about 70, a district-level event one or two. Events beat
   births and deaths; an incident listed on the "<year> in Nepal" page gets a bonus.
3. **The news piece of that day.** Wikipedia articles cite the reporting they are built on, with dates. The
   citation dated closest to the event (same day, or up to three days later), from a news outlet and sharing
   the most words with the incident, is picked: for 1 June 2001 that is The New York Times' "Royal Family of
   Nepal Is Shot Dead in Palace". From 2013 on, when no citation fits, the Nepali sites' own archives are
   searched for that day.
4. **Recent years with nothing on Wikipedia** (2014 on): the day's articles from the Nepali sites' archives
   are clustered with the radar's own engine and the story most outlets ran is shown instead.
5. **More history** (`history_sources.py`): Wikipedia's daily news pages (2002 on) add incidents with a cited
   report; nepalnews.com's daily pages of 2001-2004 (from the Wayback Machine) and the Nepali Times issue of
   that week (since 2000) give a news piece, or fill a year that has nothing else; and Kantipur's own daily
   reprint of a story from about 26 years ago is shown on top.

The answer for a date hardly changes, so it is cached in data/onthisday/MM-DD.json and recomputed after
`refresh_days`. Computing one date takes a few minutes (about 300-600 polite requests to Wikipedia).
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import math
import re
import threading
import time
from pathlib import Path

import requests

from . import history_sources as hs
from .http import USER_AGENT
from .text import terms

WIKI = "https://en.wikipedia.org/w/api.php"
WIKIDATA = "https://www.wikidata.org/w/api.php"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
NEPAL_RE = re.compile(
    r"\b(nepal|nepali|nepalese|kathmandu|lalitpur|patan|bhaktapur|pokhara|lumbini|gorkha|everest|sagarmatha|"
    r"annapurna|terai|tarai|madhesh|koshi|bagmati|gandaki|karnali|janakpur|biratnagar|birgunj|chitwan|"
    r"rana dynasty|shah dynasty|tribhuvan|mahendra|birendra|gyanendra|dipendra|koirala|prachanda|"
    r"panchayat|sherpa|gurkha|himalayan kingdom)\b", re.I)
NEWS_WORKS = re.compile(
    r"bbc|reuters|associated press|\bap\b|new york times|nytimes|guardian|washington post|times of india|hindu|"
    r"kathmandu post|himalayan times|nepali times|republica|onlinekhabar|cnn|al jazeera|afp|agence france|"
    r"time magazine|\btime\b|los angeles times|independent|telegraph|economist|wall street journal|indian express|"
    r"hindustan times|rediff|ekantipur|kantipur|xinhua|npr|abc news|cbs|nbc|deutsche welle|dw|le monde|ndtv",
    re.I)
SKIP_TITLE = re.compile(r"^(list of|lists of|timeline of|\d{4} in |\d{4}s in |outline of)|census|squads?$|"
                        r"at the \d{4} |national .* team|election results", re.I)
CITATION_NOISE = re.compile(r"retrieved|archived|accessed|\bdoi\b|isbn|issn|\bpp?\.\s*\d", re.I)

_local = threading.local()


def _session() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers["User-Agent"] = USER_AGENT + " on-this-day"
    return _local.s


def wiki(params: dict, url: str = WIKI, tries: int = 4) -> dict:
    """One MediaWiki API call, politely (maxlag, retries with back-off)."""
    p = {"format": "json", "formatversion": 2, "maxlag": 5, **params}
    for attempt in range(tries):
        try:
            r = _session().get(url, params=p, timeout=(6, 40))
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(3 * (attempt + 1))
                continue
            d = r.json()
            if d.get("error", {}).get("code") == "maxlag":
                time.sleep(float(r.headers.get("retry-after", 5)))
                continue
            return d
        except (requests.RequestException, ValueError):
            time.sleep(2 * (attempt + 1))
    return {}


# ------------------------------------------------------------------ dates in text
def date_forms(y: int, m: int, d: int) -> list[str]:
    mo = MONTHS[m - 1]
    return [f"{d} {mo} {y}", f"{mo} {d}, {y}", f"{mo} {d} {y}", f"{y}-{m:02d}-{d:02d}"]


ATTRIBUTION = re.compile(r"(post|times|news|express|herald|daily|journal|gazette|tribune|republica|khabar|reported|wrote|said)\s+(on|dated)\s+\d", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def date_sentences(text: str, y: int, m: int, d: int) -> list[str]:
    """Sentences of plain article text that contain the full date, or "25 November"/"November 25" in a
    sentence that also names the year. Reference-like sentences are skipped."""
    mo = MONTHS[m - 1]
    full = [f.lower() for f in date_forms(y, m, d)[:3]]
    short = re.compile(rf"\b({d} {mo}|{mo} {d})\b(?!\d)", re.I)
    out = []
    for para in (text or "").split("\n"):
        for s in _SENT.split(para):
            low = s.lower()
            hit = any(f in low for f in full) or (short.search(s) and re.search(rf"\b{y}\b", s))
            if hit and not CITATION_NOISE.search(s) and not ATTRIBUTION.search(s) and s[:1].isupper() and 40 <= len(s) <= 600:
                out.append(s.strip())
    return out


def kind_of(sentence: str, y: int, m: int, d: int) -> str:
    """event, birth or death. Lifespans look like "(29 December 1945 – 1 June 2001)"."""
    forms = "|".join(re.escape(f) for f in date_forms(y, m, d)[:2])
    if re.search(rf"\((?:[^()]*?;\s*)?(?:born\s+)?({forms})\s*[–-]", sentence) or re.search(rf"\bborn\b[^.]*?({forms})", sentence, re.I):
        return "birth"
    if re.search(rf"[–-]\s*({forms})\s*\)", sentence) or re.search(rf"\b(died|death|was killed|assassinated)\b", sentence, re.I) and \
            re.search(rf"[–-]\s*({forms})", sentence):
        return "death"
    return "event"


def parse_date(s: str) -> dt.date | None:
    s = re.sub(r"\[\[|\]\]", "", (s or "")).strip()
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%B %d, %Y", "%d %b %Y", "%b %d, %Y", "%B %d %Y", "%Y-%m"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------ Wikipedia pieces
class Wiki:
    """Cached lookups, shared by the worker threads of one run."""

    def __init__(self, cache_dir: Path | None = None):
        self.lock = threading.Lock()
        self.extracts: dict[str, str] = {}
        self.meta: dict[str, dict] = {}
        self.cache_dir = cache_dir

    def search(self, query: str, n: int = 8) -> list[dict]:
        d = wiki({"action": "query", "list": "search", "srsearch": query, "srlimit": n, "srprop": "snippet"})
        return (d.get("query") or {}).get("search") or []

    def extract(self, title: str) -> str:
        with self.lock:
            if title in self.extracts:
                return self.extracts[title]
        d = wiki({"action": "query", "prop": "extracts|description|pageprops", "explaintext": 1, "redirects": 1,
                  "titles": title})
        pages = (d.get("query") or {}).get("pages") or [{}]
        p = pages[0]
        text = p.get("extract") or ""
        with self.lock:
            self.extracts[title] = text
            self.meta.setdefault(title, {}).update(description=p.get("description", ""),
                                                   qid=(p.get("pageprops") or {}).get("wikibase_item", ""),
                                                   title=p.get("title", title))
        return text

    def year_page(self, y: int) -> str:
        """Wikitext of "<year> in Nepal" (cached on disk for a month; most years have no such page)."""
        path = self.cache_dir / "_years" / f"{y}.txt" if self.cache_dir else None
        if path and path.exists() and time.time() - path.stat().st_mtime < 30 * 86400:
            return path.read_text(encoding="utf-8")
        d = wiki({"action": "parse", "page": f"{y} in Nepal", "prop": "wikitext", "redirects": 1})
        text = (d.get("parse") or {}).get("wikitext", "") if "error" not in d else ""
        if path and d:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return text

    def wikitext(self, title: str) -> str:
        d = wiki({"action": "parse", "page": title, "prop": "wikitext", "redirects": 1})
        return (d.get("parse") or {}).get("wikitext", "")

    def sitelinks(self, titles: list[str]) -> dict[str, int]:
        """Number of Wikipedia language editions with an article on each title."""
        qids = {}
        missing = [t for t in titles if not self.meta.get(t, {}).get("qid")]
        for i in range(0, len(missing), 50):
            d = wiki({"action": "query", "prop": "pageprops|description", "redirects": 1, "titles": "|".join(missing[i:i + 50])})
            q = d.get("query") or {}
            back = {r["to"]: r["from"] for r in q.get("redirects") or []}
            for p in q.get("pages") or []:
                t = back.get(p.get("title"), p.get("title"))
                self.meta.setdefault(t, {}).update(qid=(p.get("pageprops") or {}).get("wikibase_item", ""),
                                                   description=p.get("description", ""))
        for t in titles:
            if self.meta.get(t, {}).get("qid"):
                qids[self.meta[t]["qid"]] = t
        out = {t: 0 for t in titles}
        ids = list(qids)
        for i in range(0, len(ids), 50):
            d = wiki({"action": "wbgetentities", "ids": "|".join(ids[i:i + 50]), "props": "sitelinks"}, url=WIKIDATA)
            for qid, e in (d.get("entities") or {}).items():
                n = sum(1 for k in (e.get("sitelinks") or {}) if k.endswith("wiki") and k not in ("commonswiki", "specieswiki"))
                out[qids.get(qid, "")] = n
        out.pop("", None)
        return out


_LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")


def clean_wikitext(s: str) -> str:
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"\{\{convert\|([\d.,]+)\|(\w+)[^}]*\}\}", r"\1 \2", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = _LINK.sub(lambda m: m.group(2) or m.group(1), s)
    s = re.sub(r"'{2,}", "", s)
    return re.sub(r"\s+", " ", s).strip(" *:-–")


def year_page_items(wikitext: str, m: int, d: int) -> list[dict]:
    """Lines of a "<year> in Nepal" page dated to this day, outside its births/deaths sections."""
    mo = MONTHS[m - 1]
    pat = re.compile(rf"^\*+\s*(?:\[\[)?({mo} {d}|{d} {mo})(?:\]\])?\s*[-–—:]\s*(.+)$")
    out, section = [], ""
    for line in wikitext.splitlines():
        h = re.match(r"^=+\s*(.*?)\s*=+\s*$", line)
        if h:
            section = h.group(1).lower()
            continue
        mm = pat.match(line.strip())
        if not mm:
            continue
        body = mm.group(2)
        link = _LINK.search(body)
        kind = "death" if "death" in section else "birth" if "birth" in section else "event"
        out.append({"text": clean_wikitext(body), "title": link.group(1).strip() if link else "", "kind": kind})
    return out


# ------------------------------------------------------------------ candidates for one year
def candidates(w: Wiki, y: int, m: int, d: int, max_checks: int = 5) -> list[dict]:
    """Nepal incidents dated y-m-d on Wikipedia, each with the sentence that dates it."""
    found: dict[str, dict] = {}
    for it in year_page_items(w.year_page(y), m, d):
        key = it["title"] or it["text"][:60]
        found[key] = {"year": y, "title": it["title"], "sentence": it["text"], "kind": it["kind"], "listed": True}
    hits, seen = [], set()
    for f in date_forms(y, m, d)[:2]:
        for h in w.search(f'"{f}" nepal'):
            if h["title"] not in seen:
                seen.add(h["title"])
                hits.append(h)
    # A curated line is often just the article's name ("Nepalese royal massacre."): use the article's own
    # sentence for that date when it has one.
    for c in found.values():
        if c["title"] and len(c["sentence"]) < 80:
            text = w.extract(c["title"])
            sents = date_sentences(text, y, m, d)
            if sents:
                c["sentence"] = sents[0]
                c["lead"] = in_lead(text, sents[0])
    checked = 0
    for h in hits:
        t = h["title"]
        if SKIP_TITLE.search(t) or t in found:
            continue
        if checked >= max_checks:
            break
        checked += 1
        text = w.extract(t)
        sents = date_sentences(text, y, m, d)
        if not sents:
            continue
        desc = w.meta.get(t, {}).get("description", "")
        # The sentence with the date names Nepal, or the article itself is about Nepal (its title or
        # Wikipedia's one-line description says so): a British diplomat's career does not qualify because
        # she once served in Kathmandu.
        about_nepal = bool(NEPAL_RE.search(f"{t} {desc}"))
        sents = [s for s in sents if NEPAL_RE.search(s)] or (sents if about_nepal else [])
        if not sents:
            continue
        s = sents[0]
        found[t] = {"year": y, "title": t, "sentence": s, "kind": kind_of(s, y, m, d), "listed": False,
                    "description": desc, "lead": in_lead(text, s)}
    # Lines of the year page without a link still count; give them the year page itself as their article.
    for c in found.values():
        if not c["title"]:
            c["title"] = f"{y} in Nepal"
    return list(found.values())


ACTION = re.compile(
    r"\b(promulgat\w*|struck|strikes?|killed|kill\w*|assassinat\w*|massacre\w*|crash\w*|declar\w*|abolish\w*|"
    r"crown\w*|signed|signs|elected|launch\w*|attack\w*|captur\w*|establish\w*|founded|inaugurat\w*|resign\w*|"
    r"dissolv\w*|overthr\w*|abdicat\w*|proclaim\w*|banned|erupt\w*|flood\w*|collaps\w*|summit\w*|reached|"
    r"won|defeat\w*|protest\w*|coup|treaty|agreement|accord|ceasefire|surrender\w*|arrested|executed|"
    r"hijack\w*|landed|opened|became|introduced|adopted by|passed)\b", re.I)


ON_DATE = re.compile(r"\bon (?:the )?(?:\d{1,2} [A-Z][a-z]+|[A-Z][a-z]+ \d{1,2},?) \d{4}")


def in_lead(text: str, sentence: str) -> bool:
    """Is the sentence in the article's opening paragraphs? Then the article is about this incident, not an
    article about something else that mentions it in passing (the flag of Nepal, adopted with a constitution)."""
    i = (text or "").find(sentence[:60])
    return 0 <= i < 1500


def rank(c: dict, links: int) -> float:
    s = math.log1p(links)
    if not c.get("lead") and not c.get("listed"):
        s *= 0.6
    s *= {"event": 1.0, "death": 0.75, "birth": 0.55}.get(c["kind"], 1.0)
    if c.get("listed"):
        s += 1.0
    if ACTION.search(c.get("sentence", "")):
        s += 0.6                                     # the sentence reports something happening
    if ON_DATE.search(c.get("sentence", "")):
        s += 0.3                                     # "... on 9 November 1990": the date is when it happened
    if NEPAL_RE.search(c["title"]):
        s += 0.4
    if re.match(r"^\d{4} in Nepal$", c["title"]):
        s += 0.5                                     # unlinked line of the curated page: still a real event
    return round(s, 3)


# ------------------------------------------------------------------ the news piece of that day
_CITE = re.compile(r"\{\{\s*[Cc]ite[ _](news|web|magazine|journal|press release)(.*?)\}\}", re.S)


def cited_news(wikitext: str, day: dt.date, about: str) -> dict | None:
    """The citation in an article that best reports the incident on its day: dated the same day or up to three
    days after (one day before, for time zones), from a news outlet, sharing words with the incident."""
    want = terms(about)
    best, best_s = None, -1e9
    from .text import date_from_url
    for ctype, body in _CITE.findall(wikitext or ""):
        f = {k.strip().lower(): v.strip() for k, v in re.findall(r"\|\s*([a-zA-Z\-]+)\s*=\s*([^|]*)", body)}
        url, title = f.get("url", ""), clean_wikitext(f.get("title", ""))
        when = parse_date(f.get("date", "")) or parse_date(f.get("publication-date", ""))
        if not url or not title or not when:
            continue
        gap = (when - day).days
        if not -1 <= gap <= 3:
            continue
        work = clean_wikitext(f.get("work") or f.get("newspaper") or f.get("website") or f.get("publisher") or f.get("agency") or "")
        newsy = ctype in ("news", "magazine") or bool(NEWS_WORKS.search(f"{work} {url}")) or bool(date_from_url(url))
        if not newsy:
            continue                             # a statute text or an NGO page is not "the news of that day"
        s = -abs(gap) * 0.8 + 1.5 * len(want & terms(title)) + (1.5 if NEWS_WORKS.search(f"{work} {url}") else 0)
        if gap < 0:
            s -= 0.5
        if s > best_s:
            best_s, best = s, {"title": title, "url": f.get("archive-url") if "dead" in f.get("url-status", "") and f.get("archive-url") else url,
                               "outlet": work or re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", url), "date": when.isoformat(),
                               "kind": "cited"}
    return best


def archive_news(cfg: dict, day: dt.date, about: str) -> dict | None:
    """From 2013 on: search the Nepali sites' own archives for the incident on that day and the next."""
    from .sources import wordpress
    words = [w for w in sorted(terms(about), key=len, reverse=True) if not w.isdigit()][:3]
    if not words:
        return None
    for site in cfg.get("archive", {}).get("wordpress", []):
        if site.get("lang") != "en":
            continue
        try:
            arts = wordpress.fetch_range(site, dt.datetime.combine(day, dt.time(0)),
                                         dt.datetime.combine(day + dt.timedelta(days=2), dt.time(0)),
                                         search=" ".join(words[:2]), max_pages=1)
        except Exception:
            continue
        if arts:
            a = arts[0]
            return {"title": a.title, "url": a.url, "outlet": a.outlet, "date": a.published[:10], "kind": "archive"}
    return None


def best_match(items: list[dict], about: str, min_shared: int = 2) -> dict | None:
    """The item whose title (and first lines) shares the most words with the incident, if enough."""
    want = terms(about)
    scored = [(len(want & terms(f"{i.get('title', '')} {i.get('dek', '')} {i.get('text', '')[:200]}")), n, i)
              for n, i in enumerate(items)]
    scored = [x for x in scored if x[0] >= min_shared]
    return max(scored, key=lambda x: (x[0], -x[1]))[2] if scored else None


def wayback_news(story: dict) -> dict:
    return {"title": story["title"], "url": story["url"], "outlet": "nepalnews.com", "date": story["date"].isoformat(),
            "kind": "wayback"}


def nt_news(issue: dict, art: dict) -> dict:
    return {"title": art["title"] + (f": {art['dek']}" if art.get("dek") and len(art["title"]) < 30 else ""),
            "url": art["url"], "outlet": f"Nepali Times #{issue['number']}", "date": issue["published"].isoformat(),
            "kind": "nepalitimes"}


def top_story(cfg: dict, day: dt.date) -> dict | None:
    """When Wikipedia has nothing for a recent year: the story most Nepali outlets ran that day, found by
    clustering the day's articles from the sites' archives with the radar's own engine."""
    from .cluster import cluster
    from .sources import wordpress
    res = wordpress.fetch_day(cfg.get("archive", {}).get("wordpress", []), day)
    if len(res.articles) < 10:
        return None
    c = cfg.get("clustering", {})
    stories = cluster(res.articles, c.get("threshold", 0.18), c.get("min_shared_terms", 1), c.get("dek_weight", 0.5),
                      c.get("nameless_penalty", 0.1))
    excl = [k.lower() for k in cfg.get("exclude_title", [])]
    stories = [s for s in stories if not any(k in s.headline.lower() for k in excl)]
    if not stories:
        return None
    best = max(stories, key=lambda s: (len(s.outlets), len(s.articles)))
    if len(best.outlets) < 2 and len(best.articles) < 3:
        return None
    en = [a for a in best.articles if a.lang == "en"]
    rep = en[0] if en else next(a for a in best.articles if a.url == best.url)
    return {"year": day.year, "title": "", "sentence": rep.title if rep.lang == "en" else best.headline,
            "kind": "top_story", "listed": False,
            "links": len(best.outlets), "score": round(math.log1p(len(best.outlets)), 3),
            "outlets": best.outlets, "article_count": len(best.articles),
            "news": {"title": rep.title, "url": rep.url, "outlet": rep.outlet, "date": rep.published[:10], "kind": "top_story"}}


# ------------------------------------------------------------------ one date
def compute(cfg: dict, month: int, day: int, years: list[int], cache_dir: Path | None = None, log=print,
            workers: int = 4) -> dict:
    w = Wiki(cache_dir)
    oc = cfg.get("onthisday", {})
    t0 = time.time()

    def one_year(y):
        try:
            dt.date(y, month, day)
        except ValueError:                       # 29 February in a common year
            return []
        try:
            cs = candidates(w, y, month, day, oc.get("max_checks", 5))
        except Exception as e:  # one bad year never stops the rest
            log(f"  {y}: skipped ({type(e).__name__})")
            return []
        if y >= oc.get("current_events_from", 2002):
            try:
                by_title = {c["title"]: c for c in cs}
                for it in hs.current_events(wiki, dt.date(y, month, day), NEPAL_RE):
                    if it["title"] in by_title:
                        by_title[it["title"]].setdefault("ce_news", it["news"])
                        continue
                    c = {"year": y, "title": it["title"], "sentence": it["sentence"], "kind": "event", "listed": True,
                         "lead": True, "source": "current_events", "ce_news": it["news"]}
                    cs.append(c)
                    by_title[it["title"]] = c
            except Exception as e:
                log(f"  {y}: daily news page skipped ({type(e).__name__})")
        return cs

    with cf.ThreadPoolExecutor(workers) as ex:
        per_year = dict(zip(years, ex.map(one_year, years)))
    titles = sorted({c["title"] for cs in per_year.values() for c in cs if c["title"]})
    links = w.sitelinks(titles) if titles else {}
    chosen: list[dict] = []
    for y, cs in per_year.items():
        if not cs:
            continue
        for c in cs:
            c["links"] = links.get(c["title"], 0)
            if c.get("source") == "current_events" and c["title"].lower() in hs.GENERIC_TOPICS:
                c["links"] = min(c["links"], 10)
            c["score"] = rank(c, c["links"])
        cs.sort(key=lambda c: -c["score"])
        best = cs[0]
        best["also"] = [{"title": c["title"], "sentence": c["sentence"], "kind": c["kind"]} for c in cs[1:4]]
        chosen.append(best)
    log(f"  Wikipedia: {sum(len(v) for v in per_year.values())} dated incidents, {len(chosen)} years with one "
        f"({time.time() - t0:.0f}s)")

    wb = oc.get("nepalnews_wayback") or {}
    wb_years = range(wb.get("from", 2001), wb.get("to", 2004) + 1) if wb else range(0)
    nt = hs.NepaliTimes(cache_dir) if oc.get("nepali_times", True) else None
    wb_cache: dict[int, list] = {}
    wb_lock = threading.Lock()

    def nepalnews(y):
        with wb_lock:
            if y in wb_cache:
                return wb_cache[y]
        try:
            stories = hs.nepalnews_day(dt.date(y, month, day), cache_dir)
        except Exception:
            stories = []
        with wb_lock:
            wb_cache[y] = stories
        return stories

    def nt_issue(y):
        try:
            return nt.for_day(dt.date(y, month, day)) if nt and y >= hs.NT_FIRST.year else None
        except Exception:
            return None

    def news_for(c):
        when = dt.date(c["year"], month, day)
        about = f"{c['sentence']} {c['title']}"
        n = None
        if c["title"] and not re.match(r"^\d{4} in Nepal$", c["title"]):
            n = cited_news(w.wikitext(c["title"]), when, about)
        if not n and re.match(r"^\d{4} in Nepal$", c["title"]):
            n = cited_news(w.year_page(c["year"]), when, about)
        if not n and c.get("ce_news"):
            n = c["ce_news"]                     # the report Wikipedia's daily news page cites
        if not n and c["year"] in wb_years:
            s = best_match(nepalnews(c["year"]), about)
            n = wayback_news(s) if s else None
        if not n and c["year"] >= 2013 and oc.get("search_archives", True):
            n = archive_news(cfg, when, about)
        if not n:
            issue = nt_issue(c["year"])
            a = best_match(issue["articles"], about) if issue else None
            n = nt_news(issue, a) if a else None
        return n

    with cf.ThreadPoolExecutor(workers) as ex:
        for c, n in zip(chosen, ex.map(news_for, chosen)):
            c["news"] = n
            c["url"] = "https://en.wikipedia.org/wiki/" + c["title"].replace(" ", "_") if c["title"] else ""
            c.pop("ce_news", None)
    have = {c["year"] for c in chosen}
    # Years with nothing on Wikipedia: nepalnews.com's lead story of the day (2001-2004) ...
    for y in [y for y in years if y in wb_years and y not in have]:
        stories = nepalnews(y)
        if stories:
            s = stories[0]
            first = re.split(r"(?<=[.!?])\s", s["text"], maxsplit=1)[0] if s["text"] else ""
            chosen.append({"year": y, "title": "", "sentence": s["title"] + (f": {first}" if first else ""),
                           "kind": "day_news", "listed": False, "links": 0, "score": 0.5, "url": "",
                           "also": [{"title": "", "sentence": x["title"], "kind": "day_news"} for x in stories[1:4]],
                           "news": wayback_news(s)})
            have.add(y)
    if oc.get("top_stories", True):
        recent = [y for y in years if y >= oc.get("top_story_from", 2014) and y not in have]
        for y in recent:
            try:
                ts = top_story(cfg, dt.date(y, month, day))
            except Exception as e:
                log(f"  {y}: top story skipped ({type(e).__name__})")
                continue
            if ts:
                chosen.append(ts)
                have.add(y)
    # ... and, since July 2000, the Nepali Times headline of that week.
    if nt:
        left = [y for y in years if y >= hs.NT_FIRST.year and y not in have]
        with cf.ThreadPoolExecutor(workers) as ex:
            issues = list(ex.map(nt_issue, left))
        for y, issue in zip(left, issues):
            if not issue or not issue["articles"]:
                continue
            a = issue["articles"][0]
            chosen.append({"year": y, "title": "", "sentence": a["title"] + (f": {a['dek']}" if a.get("dek") else ""),
                           "kind": "weekly", "listed": False, "links": 0, "score": 0.3, "url": "",
                           "news": nt_news(issue, a)})
        nt.save()
    chosen.sort(key=lambda c: -c["year"])
    log(f"  done: {len(chosen)} years, {sum(1 for c in chosen if c.get('news'))} with a news piece ({time.time() - t0:.0f}s)")
    return {"month": month, "day": day, "label": f"{day} {MONTHS[month - 1]}",
            "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "years_checked": [min(years), max(years)] if years else [], "items": chosen}


def for_date(cfg: dict, date: dt.date, cache_dir: Path, force: bool = False, log=print) -> dict:
    """The on-this-day page for a date, from the cache when it is fresh enough."""
    oc = cfg.get("onthisday", {})
    path = cache_dir / f"{date.month:02d}-{date.day:02d}.json"
    out = None
    if path.exists() and not force:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(cached["computed_at"])
            if age.days < oc.get("refresh_days", 60) and cached.get("years_checked", [0, 0])[1] >= date.year - 1:
                out = cached
        except (ValueError, KeyError):
            pass
    changed = out is None
    if out is None:
        years = list(range(oc.get("from_year", 1920), date.year))
        log(f"On this day: {date.day} {MONTHS[date.month - 1]}, {years[0]}-{years[-1]}")
        out = compute(cfg, date.month, date.day, years, cache_dir, log=log, workers=oc.get("workers", 4))
    # Kantipur's reprint for the date: its listing only holds about the last month, and the day's story may
    # appear after the morning run, so it is looked for until found.
    recent = 0 <= (nepal_today() - date).days <= 30
    if oc.get("kantipur_archive", True) and recent and (out.get("kantipur") or {}).get("date") != date.isoformat():
        try:
            k = hs.kantipur_pick(date)
        except Exception as e:
            k = None
            log(f"  Kantipur archive skipped ({type(e).__name__})")
        if k:
            out["kantipur"] = k
            changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def nepal_today(now: dt.datetime | None = None) -> dt.date:
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now + dt.timedelta(hours=5, minutes=45)).date()


def highlights(page: dict, n: int = 5) -> list[dict]:
    """The best-known items of the page, for the digest."""
    return sorted(page.get("items", []), key=lambda c: -c.get("score", 0))[:n]
