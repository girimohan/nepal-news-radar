"""Nepal-specific behaviour: Nepali text, the Nepali portals' feeds, GDELT, WordPress archives, the archive store."""
import datetime as dt
import json
from pathlib import Path

import yaml

from nepalradar import archive, llm, pipeline, report
from nepalradar.cluster import cluster
from nepalradar.models import Article
from nepalradar.scoring import score
from nepalradar.sources import SourceResult, feeds, gdelt, wordpress
from nepalradar.text import date_from_url, has_keyword, terms

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
NOW = dt.datetime(2026, 11, 25, 12, 0, tzinfo=dt.timezone.utc)


def art(outlet, title, url, hours_ago=3, lang="ne", summary="", source="feed", weight=0.9):
    return Article(source=source, source_id=f"{outlet}:{title[:20]}", outlet=outlet, title=title, url=url,
                   published=(NOW - dt.timedelta(hours=hours_ago)).isoformat(timespec="seconds"), summary=summary,
                   lang=lang, region="Nepal", weight=weight)


# ------------------------------------------------------------------ Nepali text
def test_nepali_terms_strip_joined_postpositions():
    t = terms("सर्वोच्च अदालतले दानबहादुर कार्कीको रिटमा अन्तरिम आदेश दिएन। सरकारको निर्णय")
    assert {"अदालत", "कार्की", "रिट", "सरकार", "अन्तरिम", "आदेश"} <= t
    assert "को" not in t and "।" not in "".join(t)
    assert "2082" in terms("२०८२ सालको बजेट")          # Devanagari digits read as numbers


def test_nepali_keywords_match_whole_words_with_postpositions():
    assert has_keyword("भूकम्पमा परेकाहरूको उद्धार", "भूकम्प")
    assert has_keyword("नेपालको अर्थतन्त्र", "नेपाल")
    assert not has_keyword("कर्णाली प्रदेश", "कर")        # "tax" is not the start of a province's name
    assert not has_keyword("thailand said", "ai")


def test_date_from_url():
    assert date_from_url("https://kathmandupost.com/national/2026/11/25/x") == "2026-11-25T06:15:00+00:00"
    assert date_from_url("https://english.khabarhub.com/2026/25/577008") == ""


# ------------------------------------------------------------------ feeds
def test_broken_feeds_are_repaired():
    bare_amp = b"""<?xml version="1.0"?><rss><channel><item><title>Trade & transit deal&nbsp;signed</title>
      <link>https://kathmandupost.com/money/2026/11/25/trade?a=1&b=2</link><description>Nepal &rsquo;s deal</description>
      </item></channel></rss>"""
    a = feeds.parse_feed(bare_amp, {"name": "KP"})
    assert a[0].title == "Trade & transit deal signed" and a[0].published.startswith("2026-11-25")
    unbound = b"""\n\n<?xml version="1.0"?><rss><channel><item><title><![CDATA[Meat traders protest]]></title>
      <link>https://english.ratopati.com/story/1</link><pubDate>Wed, 25 Nov 2026 13:48:22 +0000</pubDate>
      <media:content url="x"/></item></channel></rss>"""
    b = feeds.parse_feed(unbound, {"name": "Ratopati English"})
    assert b[0].title == "Meat traders protest" and b[0].published == "2026-11-25T13:48:22+00:00"


def test_require_any_keeps_only_nepal_items():
    xml = b"""<rss><channel>
      <item><title>India pledges $1.6bn to Nepal</title><link>https://bbc.co.uk/1</link></item>
      <item><title>Japan election result</title><link>https://bbc.co.uk/2</link></item></channel></rss>"""
    a = feeds.parse_feed(xml, {"name": "BBC Asia", "require_any": ["nepal", "kathmandu"]})
    assert [x.url for x in a] == ["https://bbc.co.uk/1"]


def test_undated_feed_items_get_first_seen_time():
    a = [Article("feed", "1", "Annapurna Post", "x", "https://annapurnapost.com/story/1")]
    seen = {}
    feeds.date_undated({"undated": "first_seen"}, a, seen, "2026-11-25T10:00:00+00:00")
    assert a[0].published == "2026-11-25T10:00:00+00:00"
    b = [Article("feed", "1", "Annapurna Post", "x", "https://annapurnapost.com/story/1")]
    feeds.date_undated({"undated": "first_seen"}, b, seen, "2026-11-26T10:00:00+00:00")
    assert b[0].published == "2026-11-25T10:00:00+00:00"      # remembered, not refreshed


# ------------------------------------------------------------------ GDELT and WordPress
def test_gdelt_parse_and_query():
    data = {"articles": [
        {"url": "https://www.thehindu.com/x", "title": "Earthquake strikes Nepal's Koshi Province", "seendate": "20261124T023000Z",
         "domain": "thehindu.com", "language": "English", "sourcecountry": "India"},
        {"url": "https://kathmandupost.com/y", "title": "skip me", "seendate": "20261124T023000Z", "domain": "kathmandupost.com",
         "language": "English", "sourcecountry": "Nepal"}]}
    a = gdelt.parse(data, {"skip_domains": ["kathmandupost.com"], "weight": 0.6})
    assert len(a) == 1 and a[0].outlet == "thehindu.com" and a[0].region == "India"
    assert a[0].published == "2026-11-24T02:30:00+00:00" and a[0].lang == "en" and a[0].source == "gdelt"
    assert gdelt.build_query("nepal", ["english", "nepali"]) == "nepal (sourcelang:english OR sourcelang:nepali)"


def test_wordpress_parse():
    posts = [{"id": 5, "date_gmt": "2023-03-01T17:07:11", "link": "https://www.onlinekhabar.com/2023/03/1",
              "title": {"rendered": "ओलीको अडानमा &#8216;समर्थन&#8217;"}, "excerpt": {"rendered": "<p>काठमाडौं ।</p>"}}]
    a = wordpress.parse(posts, {"name": "Onlinekhabar", "lang": "ne"})
    assert a[0].published == "2023-03-01T17:07:11+00:00" and a[0].title == "ओलीको अडानमा ‘समर्थन’"
    assert a[0].summary == "काठमाडौं ।" and a[0].lang == "ne"


# ------------------------------------------------------------------ archive
def test_archive_add_dedupe_and_search(tmp_path):
    root = tmp_path / "archive"
    a = [art("Onlinekhabar", "पूर्वी नेपालमा भूकम्प, क्षति विवरण आउन बाँकी", "https://www.onlinekhabar.com/1", 30),
         art("The Kathmandu Post", "5.3 magnitude earthquake hits Koshi Province", "https://kathmandupost.com/2", 30, lang="en"),
         art("Setopati", "बजेट कार्यान्वयनमा ढिलाइ", "https://www.setopati.com/3", 2)]
    added = archive.add(root, a)
    assert sum(added.values()) == 3
    assert sum(archive.add(root, a).values()) == 0             # same links are not stored twice
    hits = archive.search(root, ["भूकम्प", "earthquake"], NOW.date() - dt.timedelta(days=3), NOW.date())
    assert {h["outlet"] for h in hits} == {"Onlinekhabar", "The Kathmandu Post"}
    assert len(archive.search(root, ["भूकम्प", "koshi"], NOW.date() - dt.timedelta(days=3), NOW.date(), match="all")) == 0
    assert len(archive.search(root, [], NOW.date(), NOW.date(), lang="ne")) == 1
    idx = json.loads((root / "index.json").read_text(encoding="utf-8"))
    assert idx["total"] == 3 and idx["first"] <= idx["last"]


# ------------------------------------------------------------------ clustering real Nepali headlines
KARKI = ["दानबहादुर कार्कीको रिटमा अन्तरिम आदेश दिन अस्वीकार",
         "दानबहादुर कार्कीको रिटमा सर्वोच्चले अन्तरिम आदेश दिएन",
         "दानबहादुरलाई पदबाट हटाउने सरकारको निर्णय यथावत, अन्तरिम आदेश अस्वीकार",
         "दानबहादुर कार्कीको मुद्दामा अन्तरिम आदेश जारी गर्न अस्वीकार"]
CHOYING = ["लुम्बिनी विकास कोषमा आनी छोइङको नियुक्तिविरुद्ध सर्वोच्चले माग्यो लिखित जवाफ",
           "लुम्बिनी विकास कोषकी उपाध्यक्ष आनी छोइङ डोल्मा विरूद्धको रिटमा सर्वोच्चले दियो कारण देखाउ आदेश"]
SQUATTERS = ["शनिबारसम्म होल्डिङ सेन्टर खाली गर्न सुकुम्बासीलाई सरकारको उर्दी",
             "सुकुम्बासीलाई दुई दिनभित्र होल्डिङ सेन्टर खाली गर्न प्रशासनको निर्देशन"]


def nepali_day():
    outlets = ["Onlinekhabar", "Ratopati", "Nagarik News", "Setopati", "Khabarhub", "Baahrakhari"]
    out = []
    for group in (KARKI, CHOYING, SQUATTERS):
        for i, t in enumerate(group):
            out.append(art(outlets[i], t, f"https://{outlets[i].lower().replace(' ', '')}.com/{len(out)}", 1 + len(out) % 5))
    return out


def test_nepali_headlines_cluster_into_their_stories():
    stories = cluster(nepali_day(), CFG["clustering"]["threshold"], CFG["clustering"]["min_shared_terms"],
                      CFG["clustering"]["dek_weight"], CFG["clustering"]["nameless_penalty"])
    groups = sorted(sorted(a.title for a in s.articles) for s in stories)
    assert sorted(KARKI) in groups and sorted(CHOYING) in groups and sorted(SQUATTERS) in groups
    assert len(stories) == 3      # two Supreme Court stories stay apart


def test_pipeline_on_nepal_config(tmp_path):
    arts = nepali_day() + [
        art("The Kathmandu Post", "Bangladesh minimum wage hike sparks fresh protests",
            "https://kathmandupost.com/world/2026/11/25/bangladesh", 2, lang="en"),
        art("Onlinekhabar", "आजको राशिफल", "https://www.onlinekhabar.com/rashifal", 2)]
    p = pipeline.run(CFG, tmp_path / "docs" / "news.json", now=NOW, ledger_path=tmp_path / "data" / "seen.json",
                     reader=llm.Reader(api_key=""), results=[SourceResult("feeds", arts)],
                     archive_root=tmp_path / "docs" / "archive")
    heads = [s["headline"] for s in p["stories"]]
    assert any("कार्की" in h for h in heads) and p["stories"][0]["outlet_count"] == 4
    assert p["stories"][0]["topic"] == "Politics & government" and p["stories"][0]["langs"] == ["ne"]
    assert not any("Bangladesh" in h for h in heads)              # world page of a Nepali paper
    assert p["funnel"]["excluded"] == 2 and p["funnel"]["archived_new"] == 8
    md = report.digest(p)
    assert md.startswith("# Nepal news radar") and "नेपाली press only" in md


def test_story_topic_is_its_strongest_match():
    s = cluster([art("Onlinekhabar", "१०औं राष्ट्रिय खेलकुद : महिला बास्केटबलमा सुदूरपश्चिम क्वाटरफाइनलमा", "https://a/1"),
                 art("Ratopati", "दसौँ राष्ट्रिय खेलकुद : महिला बास्केटबलतर्फ सुदूरपश्चिम क्वाटर फाइनलमा", "https://b/1")])[0]
    score(s, CFG, NOW)
    assert s.topic == "Sports & culture" and "Society, law & health" in s.topics


def test_brief_schema_is_english_and_nepal_scoped():
    assert "scope" in llm.SCHEMA["required"] and "finland_link" not in llm.SCHEMA["properties"]
    assert "Nepali" in llm.SYSTEM and "English" in llm.SYSTEM


def test_gdelt_splits_full_windows(monkeypatch):
    calls = []

    def fake(q, start=None, end=None, timespan="", **kw):
        if timespan:                                      # the fast first query: full, so the window is split
            start, end = NOW - dt.timedelta(hours=int(timespan[:-1])), NOW
        calls.append((start, end))
        hours = (end - start).total_seconds() / 3600
        n = 250 if hours > 12 else 40                     # anything longer than 12 h comes back full
        return {"articles": [{"url": f"https://x.in/{start:%d%H}/{i}", "title": "Nepal story", "seendate": f"{start:%Y%m%dT%H%M%S}Z",
                              "domain": "x.in", "language": "English", "sourcecountry": "India"} for i in range(n)]}
    monkeypatch.setattr(gdelt, "query", fake)
    r = gdelt.fetch({}, 48, now=NOW)
    assert r.ok and len(calls) == 8                       # last 48 h, then 48 -> 24+24 -> four 12 h pieces
    assert len(r.articles) == 250 + 3 * 40               # the first answer is kept; one piece repeats its links


def test_gdelt_keeps_first_answer_when_split_fails(monkeypatch):
    def fake(q, start=None, end=None, timespan="", **kw):
        if not timespan:
            raise gdelt.FetchError("ReadTimeout")
        return {"articles": [{"url": f"https://x.in/{i}", "title": "Nepal", "seendate": "20261125T050000Z",
                              "domain": "x.in", "language": "English"} for i in range(250)]}
    monkeypatch.setattr(gdelt, "query", fake)
    r = gdelt.fetch({}, 48, now=NOW)
    assert r.ok and len(r.articles) == 250 and "newest 250 only" in r.detail


# ------------------------------------------------------------------ on this day
from nepalradar import onthisday as otd  # noqa: E402


def test_date_sentences_skip_references_and_find_both_spellings():
    text = ("The Nepalese royal massacre was a mass shooting which occurred on 1 June 2001 at Narayanhiti Palace.\n"
            "Smith, J. (1 June 2001). Retrieved 3 June 2001.\n"
            "On June 1, 2001, ten members of the royal family were killed.")
    s = otd.date_sentences(text, 2001, 6, 1)
    assert len(s) == 2 and "Retrieved" not in " ".join(s)
    assert otd.date_sentences("Nothing happened on 2 June 2001.", 2001, 6, 1) == []


def test_kind_of_lifespans():
    assert otd.kind_of("Birendra (29 December 1945 – 1 June 2001) was King of Nepal.", 2001, 6, 1) == "death"
    assert otd.kind_of("Queen Komal (born 18 February 1951) is a member of the royal family.", 1951, 2, 18) == "birth"
    assert otd.kind_of("A 7.8 earthquake struck Nepal on 25 April 2015.", 2015, 4, 25) == "event"


def test_year_page_items_keep_section_kinds():
    wt = """== Events ==
* June 1 - [[Nepalese royal massacre]].
* June 4 - [[Gyanendra of Nepal|Prince Gyanendra]] is crowned King.
== Deaths ==
* June 1 - [[Birendra of Nepal]], king"""
    items = otd.year_page_items(wt, 6, 1)
    assert [(i["title"], i["kind"]) for i in items] == [("Nepalese royal massacre", "event"), ("Birendra of Nepal", "death")]
    assert otd.year_page_items(wt, 6, 4)[0]["text"] == "Prince Gyanendra is crowned King."


def test_cited_news_picks_the_report_of_that_day():
    wt = """{{cite news |title=Royal Family of Nepal Is Shot Dead in Palace |work=The New York Times |date=2001-06-02 |url=https://www.nytimes.com/2001/06/02/world/x.html}}
{{cite web |title=Nepal Constitution text |date=2001-06-01 |url=https://example.org/constitution}}
{{cite news |title=Inquiry blames crown prince |work=The Guardian |date=2001-06-14 |url=https://www.theguardian.com/y}}
{{cite news |title=Nepal mourns slain king |work=BBC News |date=2 June 2001 |url=http://news.bbc.co.uk/z}}"""
    n = otd.cited_news(wt, dt.date(2001, 6, 1), "royal family shot dead massacre palace")
    assert n["outlet"] == "The New York Times" and n["date"] == "2001-06-02"
    assert otd.cited_news(wt, dt.date(2001, 5, 1), "x") is None      # nothing dated near that day


def test_rank_prefers_famous_events_reported_in_the_lead():
    massacre = {"title": "Nepalese royal massacre", "kind": "event", "lead": True, "sentence": "A mass shooting occurred on 1 June 2001."}
    flag = {"title": "Flag of Nepal", "kind": "event", "lead": False, "sentence": "The flag was specified in the constitution adopted 9 November 1990."}
    birth = {"title": "Somebody", "kind": "birth", "lead": True, "sentence": "Somebody (born 1 June 2001) is a cricketer from Nepal."}
    assert otd.rank(massacre, 40) > otd.rank(flag, 76) > otd.rank(birth, 5)


def test_for_date_uses_the_cache(tmp_path, monkeypatch):
    page = {"month": 11, "day": 25, "label": "25 November", "years_checked": [1920, 2025], "items": [],
            "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    (tmp_path / "11-25.json").write_text(json.dumps(page), encoding="utf-8")
    monkeypatch.setattr(otd, "compute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not recompute")))
    monkeypatch.setattr(otd, "nepal_today", lambda now=None: dt.date(2026, 11, 25))
    monkeypatch.setattr(otd.hs, "kantipur_pick", lambda day: {"date": day.isoformat(), "title": "[अर्काइभ]...x",
                        "url": "https://ekantipur.com/Kantipur-Archive/2026/11/25/x.html", "year": 2000, "years_ago": 26})
    page = otd.for_date(CFG, dt.date(2026, 11, 25), tmp_path)
    assert page["label"] == "25 November" and page["kantipur"]["year"] == 2000
    # found once, saved with the page: the next run does not look again
    monkeypatch.setattr(otd.hs, "kantipur_pick", lambda day: (_ for _ in ()).throw(AssertionError("looked again")))
    assert otd.for_date(CFG, dt.date(2026, 11, 25), tmp_path)["kantipur"]["years_ago"] == 26


def test_digest_has_history_section():
    page = {"label": "1 June", "items": [{"year": 2001, "kind": "event", "score": 5, "sentence": "Royal massacre.",
            "url": "https://en.wikipedia.org/wiki/Nepalese_royal_massacre", "title": "Nepalese royal massacre",
            "news": {"outlet": "The New York Times", "title": "Royal Family of Nepal Is Shot Dead", "url": "https://nyt/x", "date": "2001-06-02"}}]}
    md = "\n".join(report.history(page))
    assert "On this day in Nepal: 1 June" in md and "**2001**" in md and "The New York Times" in md


# ------------------------------------------------------------------ more history sources
from nepalradar import history_sources as hs  # noqa: E402

CE_PAGE = """{{Current events|year=2008|month=05|day=28|content=
;Armed conflicts and attacks
*[[Iraq War]]
**A bombing kills five people in Baghdad. [http://example.com/iraq-bombing-kills-five (Reuters)]
;Politics and elections
*[[Nepal]]
**The [[Nepalese Constituent Assembly]] meets for the first time. [http://news.bbc.co.uk/2/hi/south_asia/7422900.stm BBC News]
*[[Nepalese monarchy]]
**The Assembly declares Nepal a federal, democratic republic,&nbsp;abolishing the monarchy . [http://www.sify.com/news/nepal-abolishes-240-year-old-monarchy.html (Sify)]
}}"""


def test_current_events_keeps_nepal_lines_with_their_topic_and_report():
    items = hs.current_events_items(CE_PAGE, dt.date(2008, 5, 28), otd.NEPAL_RE)
    assert [i["title"] for i in items] == ["Nepalese Constituent Assembly", "Nepalese monarchy"]
    assert items[0]["news"]["outlet"] == "BBC News" and items[0]["news"]["date"] == "2008-05-28"
    assert items[1]["sentence"].endswith("abolishing the monarchy.")
    assert items[1]["news"]["title"] == "Nepal abolishes 240 year old monarchy"


NN_2001 = """<td><p><a name="14"><b><font face="Arial" size="3">CIAA
 files cases against 10 persons in Lauda deal</font></b></a></p>
 <p><font face="Arial" size="2"><b>Kathmandu, May
 25:</b> The Commission for the Investigation of Abuse of Authority filed cases at Patan appellate court Friday.</font></p>
 <hr size="1"><p><a name="15"><b>Strike called</b></a></p><p><b>Biratnagar, May 24:</b> Ten parties called a strike.</p>"""
NN_2002 = """<p><b><font size="3"><a name="13">India accuses Pakistan</a></font></b></p><p><font size="2">India Saturday
 accused Pakistan of trying to weaken the SAARC. <b><i>nepalnews.com br Nov.3</i></b></font></p><hr size="1">"""
NN_2004 = """<p><b><font size="3"><a name="1">Govt official shot in the capital&nbsp;</a></font></b></p>
 <p><font size="2">Unidentified assailants shot and injured a government official at Naya Baneshwor.</font></p><hr>"""


def test_nepalnews_pages_are_dated_by_dateline_signoff_or_file_name():
    a = hs.parse_nepalnews(NN_2001, 2001)
    assert [(s["title"], s["date"], s["place"]) for s in a] == [
        ("CIAA files cases against 10 persons in Lauda deal", dt.date(2001, 5, 25), "Kathmandu"),
        ("Strike called", dt.date(2001, 5, 24), "Biratnagar")]
    assert a[0]["text"].startswith("The Commission")
    b = hs.parse_nepalnews(NN_2002, 2002)
    assert b[0]["date"] == dt.date(2002, 11, 3) and "nepalnews.com" not in b[0]["text"]
    assert hs.parse_nepalnews(NN_2004, 2004) == []
    assert hs.parse_nepalnews(NN_2004, 2004, dt.date(2004, 6, 12))[0]["title"] == "Govt official shot in the capital"


def test_nepalnews_month_pages_and_binary_search(monkeypatch, tmp_path):
    rows = [["20010609", f"http://www.nepalnews.com.np:80/archive/2001/june/arc{n}.htm"] for n in (229, 225, 227)] + \
           [["20010609", "http://www.nepalnews.com.np:80/archive/2001/june/syp.htm"],
            ["20010609", "http://www.nepalnews.com.np:80/archive/2001/may/arc222.htm"]]
    assert [p[0] for p in hs.month_pages(rows, 6)] == [225, 227, 229]
    rows04 = [["2004", "http://www.nepalnews.com.np:80/archive/2004/june/arc_june04_12.htm"],
              ["2004", "http://www.nepalnews.com.np:80/archive/2004/june/arc_jul04_01.htm"]]
    assert [(p[0], p[1]) for p in hs.month_pages(rows04, 6)] == [(12, 12)]
    days = {225: 2, 227: 5, 229: 9}
    monkeypatch.setattr(hs, "wayback_index", lambda y, c: rows)
    fetched = []

    def fake_get(url, *a, **k):
        n = int(url.split("arc")[-1].split(".")[0])
        fetched.append(n)
        return f'<a name="1"><b>Story {n}</b></a><p><b>Kathmandu, June {days[n]}:</b> text</p>'
    monkeypatch.setattr(hs, "get", fake_get)
    got = hs.nepalnews_day(dt.date(2001, 6, 9), tmp_path)
    assert got[0]["title"] == "Story 229" and "web.archive.org/web/20010609/" in got[0]["url"]
    assert fetched == [227, 229]
    assert hs.nepalnews_day(dt.date(2001, 6, 7), tmp_path) == []


NT_ISSUE = """<h1>Issue #242</h1><p>April 8-14, 2005</p><p><strong>Published on <time datetime="2005-04-08">Apr 8, 2005</time></strong></p>
<a href="/issue/241">prev</a><a data-app-link href="/undoing">UNDOING</a><a data-app-link href="/undoing">Pressure to rollback curbs</a>
<a data-app-link href="/model-multilateralism">Model multilateralism</a><a href="/follow">Add us as a preferred source on Google</a>"""


def test_nepali_times_issue_page_and_search(monkeypatch, tmp_path):
    page = hs.parse_nt_issue(NT_ISSUE)
    assert page["published"] == dt.date(2005, 4, 8)
    assert page["articles"][0] == {"url": "https://archive.nepalitimes.com/undoing", "title": "UNDOING",
                                   "dek": "Pressure to rollback curbs"}
    assert [a["title"] for a in page["articles"]] == ["UNDOING", "Model multilateralism"]
    # Weekly issues from #1 (19 July 2000), with issue 3 missing: the search finds the first one on or after the date.
    start = dt.date(2000, 7, 19)
    calls = []

    def fake_get(url, *a, **k):
        if url.endswith("/archive"):
            return "Issue #400"
        n = int(url.rsplit("/", 1)[1])
        calls.append(n)
        if n == 3:
            return ""
        d = start + dt.timedelta(weeks=n - 1)
        return f'Published on <time>{d.strftime("%b")} {d.day}, {d.year}</time><a href="/lead-{n}">Lead story {n}</a>'
    monkeypatch.setattr(hs, "get", fake_get)
    nt = hs.NepaliTimes(tmp_path)
    issue = nt.for_day(dt.date(2005, 4, 6))
    assert issue["number"] == 247 and issue["articles"][0]["title"] == "Lead story 247"
    assert len(calls) <= 6
    nt.save()
    assert hs.NepaliTimes(tmp_path).dates[247] == issue["published"].isoformat()
    assert nt.for_day(dt.date(1999, 1, 1)) is None


def test_kantipur_years_ago_from_bikram_sambat_years():
    text = "मंसिर ८, २०८३ कान्तिपुर संवाददाता ... माओवादीले ८ असोज २०५७ मा डोल्पाको सदरमुकाम दुनै ... २०५७ सालमा"
    assert hs.bs_years_ago(text) == 26
    assert hs.years_ago("This is what the annual budget was like 26 years ago") == 26
    assert hs.bs_years_ago("मंसिर ८, २०८३") is None


def test_briefings_take_the_newest_matching_post(monkeypatch):
    posts = [{"date_gmt": "2026-11-24T14:20:56", "link": "https://english.nepalnews.com/s/daily-brief/x/",
              "title": {"rendered": "Nepal News Evening Briefing | Tuesday, November 24, 2026"},
              "excerpt": {"rendered": "<p>KATHMANDU: ...</p>"}},
             {"date_gmt": "2026-11-23T14:20:56", "link": "y", "title": {"rendered": "Nepal News Evening Briefing | Monday"}}]
    monkeypatch.setattr(hs, "get", lambda *a, **k: json.dumps(posts))
    cfg = {"briefings": [{"name": "Nepal News Evening Briefing", "base": "https://english.nepalnews.com",
                          "search": "Nepal News Evening Briefing"}]}
    b = hs.latest_briefings(cfg, now=NOW)
    assert len(b) == 1 and b[0]["url"].endswith("/x/") and b[0]["excerpt"] == "KATHMANDU: ..."
    assert hs.latest_briefings(cfg, now=NOW + dt.timedelta(days=9)) == []


def test_best_match_needs_shared_words():
    items = [{"title": "Long live the king"}, {"title": "Royal family shot dead in palace massacre"}]
    assert otd.best_match(items, "The royal massacre: King Birendra and his family are shot dead")["title"].startswith("Royal")
    assert otd.best_match(items, "Earthquake in Gorkha") is None


def test_digest_shows_kantipur_pick_and_weekly_items():
    page = {"label": "25 November", "kantipur": {"title": "[अर्काइभ]...x", "title_en": "[Archive]...Then the army was deployed",
                                                 "url": "https://k/ne", "url_en": "https://k/en", "year": 2000},
            "items": [{"year": 2003, "kind": "weekly", "score": 0.3, "sentence": "Achham's agony", "url": "",
                       "news": {"outlet": "Nepali Times #172", "title": "Achham's agony", "url": "https://nt/a",
                                "date": "2003-11-28", "kind": "nepalitimes"}}]}
    md = "\n".join(report.history(page))
    assert "Kantipur's archive pick (2000): [Then the army was deployed](https://k/en)" in md
    assert "(Nepali Times that week)" in md and "News that week: [Nepali Times #172" in md
    payload = {"stories": [], "funnel": {}, "new_today": 0, "date": "2026-11-25", "sources": [], "llm": {},
               "briefings": [{"title": "Nepal News Evening Briefing | Tuesday", "url": "https://nn/b"}]}
    assert "Daily round-ups: [Nepal News Evening Briefing | Tuesday](https://nn/b)" in report.digest(payload)
