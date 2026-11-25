"""Publisher RSS 2.0 and Atom feeds, read with the standard library only."""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import hashlib
import re
import xml.etree.ElementTree as ET
from html.entities import name2codepoint
from email.utils import parsedate_to_datetime

from ..http import FetchError, get
from ..models import Article
from ..text import canonical_url, date_from_url, has_keyword, strip_html
from . import SourceResult

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"


def parse_date(s: str | None) -> str:
    """RFC 822 (RSS) or ISO 8601 (Atom) to ISO 8601 UTC. Empty string when unreadable."""
    s = (s or "").strip()
    if not s:
        return ""
    d = None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if d is None:
        return ""
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def _text(el, *names) -> str:
    for n in names:
        x = el.find(n)
        if x is not None and (x.text or "").strip():
            return x.text.strip()
    return ""


_ENTITY = re.compile(rb"&(#\d+;|#x[0-9a-fA-F]+;|([A-Za-z][A-Za-z0-9]*);)?")
_CTRL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def repair_xml(body: bytes) -> bytes:
    """Fix what some Nepali news sites send: bare "&" in titles and links, HTML entities such as &nbsp; or
    &rsquo; that XML does not know, and stray control characters."""
    def fix(m: re.Match) -> bytes:
        if m.group(1) is None:
            return b"&amp;"                                  # a bare ampersand
        name = m.group(2)
        if name is None or name.decode() in ("amp", "lt", "gt", "quot", "apos"):
            return m.group(0)                                # numeric or one of XML's own five
        cp = name2codepoint.get(name.decode())
        return f"&#{cp};".encode() if cp else b"&amp;" + name + b";"
    return _ENTITY.sub(fix, _CTRL.sub(b"", body))


_ITEM = re.compile(rb"<item[\s>].*?</item>", re.S)
_FIELD = re.compile(rb"<(title|link|guid|pubDate|description|dc:date)(?:\s[^>]*)?>(.*?)</\1>", re.S)
_CDATA = re.compile(rb"<!\[CDATA\[(.*?)\]\]>", re.S)


def scrape_items(body: bytes):
    """Last resort for feeds that are not XML at all (undeclared namespace prefixes, text before the XML
    declaration...): pull each <item>'s fields out with regular expressions into a plain RSS tree."""
    rss = ET.Element("rss")
    ch = ET.SubElement(rss, "channel")
    for m in _ITEM.finditer(body):
        it = ET.SubElement(ch, "item")
        for name, val in _FIELD.findall(m.group(0)):
            val = _CDATA.sub(lambda c: c.group(1), val).strip()
            tag = "pubDate" if name == b"dc:date" else name.decode()
            if it.find(tag) is None:
                ET.SubElement(it, tag).text = strip_html(val.decode("utf-8", "replace"))
    if not len(ch):
        raise ET.ParseError("no <item> elements found")
    return rss


def parse_xml(body: bytes | str):
    if isinstance(body, str):
        body = body.encode("utf-8")
    body = body.lstrip(b"\xef\xbb\xbf \t\r\n")       # BOM or blank lines before <?xml ...?>
    try:
        return ET.fromstring(body)
    except ET.ParseError:
        pass
    try:
        return ET.fromstring(repair_xml(body))
    except ET.ParseError:
        return scrape_items(body)


def parse_feed(xml: bytes | str, feed: dict) -> list[Article]:
    """Items of one feed as Articles. `feed` is the entry from config.yaml (name, url, weight, region, lang,
    and optionally require_any: keep only items that mention one of these words, for international outlets)."""
    root = parse_xml(xml)
    out: list[Article] = []
    items = root.findall("./channel/item") or root.findall(".//item")
    atom = False
    if not items:
        items = root.findall(f"{ATOM}entry")
        atom = True
    for it in items:
        if atom:
            title = strip_html(_text(it, f"{ATOM}title"))
            link = ""
            for l in it.findall(f"{ATOM}link"):
                if l.get("rel", "alternate") == "alternate" and l.get("href"):
                    link = l.get("href")
                    break
            published = parse_date(_text(it, f"{ATOM}published", f"{ATOM}updated"))
            summary = strip_html(_text(it, f"{ATOM}summary", f"{ATOM}content"))
            guid = _text(it, f"{ATOM}id") or link
        else:
            title = strip_html(_text(it, "title"))
            link = _text(it, "link")
            if not link:
                g = it.find("guid")
                if g is not None and (g.text or "").startswith("http"):
                    link = g.text.strip()
            published = parse_date(_text(it, "pubDate", f"{DC}date"))
            summary = strip_html(_text(it, "description", f"{CONTENT}encoded"))
            guid = _text(it, "guid") or link
        if not title or not link:
            continue
        published = published or date_from_url(link)
        need = feed.get("require_any")
        if need and not any(has_keyword(f"{title} {summary[:600]}".lower(), k) for k in need):
            continue
        out.append(Article(
            source="feed", source_id=f"{feed['name']}:{hashlib.sha1(guid.encode()).hexdigest()[:12]}",
            outlet=feed["name"], title=title, url=link, published=published, summary=summary[:1500],
            region=feed.get("region", ""), lang=feed.get("lang", "en"), weight=float(feed.get("weight", 1.0)),
        ))
    return out


def fetch_one(feed: dict) -> tuple[dict, list[Article], str]:
    if feed.get("enabled") is False:
        return feed, [], ""
    try:
        body = get(feed["url"], raw=True)
        if body is None:
            return feed, [], "feed not found (404)"
        return feed, parse_feed(body, feed), ""
    except (FetchError, ET.ParseError) as e:
        return feed, [], f"{type(e).__name__}: {e}"[:160]


def date_undated(feed: dict, arts: list[Article], first_seen: dict | None, now_iso: str) -> None:
    """Some feeds (Annapurna Post, The Annapurna Express) give no dates. For feeds marked `undated: first_seen`
    an item is dated when the radar first saw it, remembered in `first_seen` (canonical link -> time)."""
    if feed.get("undated") != "first_seen" or first_seen is None:
        return
    for a in arts:
        if not a.published:
            a.published = first_seen.setdefault(canonical_url(a.url), now_iso)


def fetch(feeds: list[dict], workers: int = 8, first_seen: dict | None = None, now_iso: str = "") -> SourceResult:
    res = SourceResult("feeds")
    broken = []
    feeds = [f for f in feeds if f.get("enabled") is not False]
    now_iso = now_iso or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with cf.ThreadPoolExecutor(workers) as ex:
        for feed, arts, err in ex.map(fetch_one, feeds):
            date_undated(feed, arts, first_seen, now_iso)
            res.articles.extend(arts)
            if err:
                broken.append(f"{feed['name']} ({err})")
    res.detail = f"{len(feeds) - len(broken)}/{len(feeds)} feeds read"
    if broken:
        res.detail += "; failed: " + "; ".join(broken)
    if feeds and len(broken) == len(feeds):
        res.ok, res.error = False, "every feed failed"
    return res
