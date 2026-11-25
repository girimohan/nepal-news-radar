from __future__ import annotations

import html
import re
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# Latin letters and digits plus Devanagari (Nepali), without the danda (।, ॥) that ends a Nepali sentence.
DEVA = "\u0900-\u0963\u0966-\u097F"
WORDCHARS = "a-z0-9äöåü" + DEVA
_WORD = re.compile(rf"[{WORDCHARS}][{WORDCHARS}'\.\-]*[{WORDCHARS}]|[{WORDCHARS}]")
_DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Common English and Nepali words that say nothing about which story a headline is about.
STOPWORDS = frozenset("""
a about above after again against all also am an and any are as at be because been before being below between both
but by can could did do does doing down during each few for from further had has have having he her here hers him his
how i if in into is it its itself just like me more most my new no nor not now of off on once only or other our out
over own same says say said she should so some such than that the their them then there these they this those through
to too under until up very was we were what when where which while who whom why will with would you your yours
amid over vs via after gets get got make makes made big first last next week today yesterday report reports reportedly
year years day days time times may might new news update updates live latest here's heres what's whats how why
र को का की मा ले लाई बाट सँग देखि सम्म पनि नै हो छ छन् छैन थियो थिए भएको भएका भयो हुने हुन्छ गर्ने गरेको गरेका
गरी गर्न गर्दै गरे गरिने गरिएको भन्दै भने भन्छन् भनेका रहेको रहेका यो त्यो यस उक्त एक दुई तथा वा तर कि जो जुन उनी
उनले उनको हामी अब अझै आज भोलि हिजो लागि प्रति साथ पछि अघि भित्र बीच बिच माथि तल अनुसार बारे लिएर दिएर बन्ने
दिने लिने गरेर भएर हुँदै नयाँ ठूलो सबै धेरै केही अर्को आफ्नो विषयमा सम्बन्धमा
""".split())

# Postpositions and plural markers that Nepali writes joined to the noun: नेपालको, सरकारले, मन्त्रीहरूलाई.
_NE_SUFFIXES = ("हरूलाई", "हरुलाई", "हरूको", "हरुको", "हरूले", "हरुले", "हरूमा", "हरुमा", "हरू", "हरु", "द्वारा", "देखि",
                "सम्म", "लाई", "बाट", "सँग", "माथि", "भित्र", "को", "का", "की", "ले", "मा")

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_|cmp$|cmpid|ito$|at_|guccounter|ncid|sr_share|source$)")


def strip_html(s: str | None) -> str:
    """HTML (possibly double-escaped, as some feeds send it) to plain text."""
    if not s:
        return ""
    s = html.unescape(html.unescape(s))
    return _WS.sub(" ", _TAG.sub(" ", s)).strip()


_NE_SUFFIX_RE = "|".join(re.escape(x) for x in _NE_SUFFIXES + ("मै", "कै", "लाइ", "ले", "द्वारा"))


@lru_cache(maxsize=4096)
def keyword_re(keyword: str) -> re.Pattern:
    """Match a keyword only as a whole word or phrase ("ai" must not match "said" or "Thailand")."""
    body = re.escape(keyword.lower().strip()).replace(r"\ ", r"[\s\-/]+")
    # A Nepali keyword may carry a joined postposition (नेपाल -> नेपालको), but must not just be the start of a
    # longer word (कर "tax" must not match कर्णाली).
    if re.search(f"[{DEVA}]", keyword):
        return re.compile(rf"(?<![{WORDCHARS}]){body}(?:{_NE_SUFFIX_RE})?(?![{WORDCHARS}])")
    return re.compile(rf"(?<![{WORDCHARS}]){body}(?![{WORDCHARS}])")


def has_keyword(text: str, keyword: str) -> bool:
    return bool(keyword_re(keyword).search(text))


def _stem(w: str) -> str:
    """Very light stemming so "launches"/"launched"/"launch" and "models"/"model" meet, and Nepali
    "सरकारले"/"सरकारको"/"सरकार" too."""
    w = w.strip(".'-")
    if w and "ऀ" <= w[0] <= "ॿ":
        for suf in _NE_SUFFIXES:
            if w.endswith(suf) and len(w) - len(suf) >= 2:
                return w[: -len(suf)]
        return w
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 4 and w.endswith("es") and not w.endswith("ses"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    if w.endswith("'s"):
        return w[:-2]
    return w


def terms(text: str) -> set[str]:
    """Content words of a headline, lower-cased and lightly stemmed, stopwords removed."""
    out = set()
    for w in _WORD.findall((text or "").lower().replace("’", "'").translate(_DEVA_DIGITS)):
        w = w.removesuffix("'s")
        if w in STOPWORDS or len(w) < 2 or w.isdigit() and len(w) < 3:
            continue
        s = _stem(w)
        if s and s not in STOPWORDS:
            out.add(s)
    return out


def canonical_url(url: str) -> str:
    """Strip tracking parameters, fragments, "www." and trailing slashes, so the same article matches itself."""
    try:
        p = urlsplit((url or "").strip())
    except ValueError:
        return url or ""
    host = p.netloc.lower().removeprefix("www.").removeprefix("m.")
    q = urlencode([(k, v) for k, v in parse_qsl(p.query) if not _TRACKING.match(k.lower())])
    return urlunsplit(("https", host, p.path.rstrip("/") or "/", q, ""))


def domain(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


_URL_DATE = re.compile(r"/(20\d\d)/(\d{1,2})/(\d{1,2})(?:/|$)")


def date_from_url(url: str) -> str:
    """Many news sites put the date in the link (kathmandupost.com/national/2026/11/25/...). Returns that day
    at noon Nepal time (06:15 UTC) as ISO 8601, or "" when the link has no date."""
    m = _URL_DATE.search(url or "")
    if not m:
        return ""
    y, mo, d = (int(x) for x in m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return ""
    return f"{y:04d}-{mo:02d}-{d:02d}T06:15:00+00:00"
