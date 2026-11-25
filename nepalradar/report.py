"""The daily digest: a Markdown page that becomes a GitHub issue (GitHub emails it to you)."""
from __future__ import annotations

import re

BADGE = {"new": "🆕 new", "rising": "📈 rising", "steady": ""}
SCOPE = {"national": "🇳🇵 national", "local": "📍 local", "diaspora": "✈️ Nepalis abroad", "international": "🌏 international"}


def _story(i: int, s: dict) -> list[str]:
    b = s.get("brief") or {}
    head = b.get("headline") or s["headline"]
    badge = BADGE.get(s.get("status", ""), "")
    lines = [f"### {i}. [{head}]({s['url']})", "",
             f"**{s['score']:.0f}/100** · {s['topic']}" + (f" · {badge}" if badge else "")
             + (f" · {SCOPE[b['scope']]}" if b.get("scope") in SCOPE else "")
             + (" · नेपाली press only" if s.get("langs") == ["ne"] else "")]
    if b:
        lines += ["", b["summary"], "", f"*Why it matters:* {b['why_it_matters']}", f"*Angle:* {b['angle']}"]
        if b.get("confidence") == "low":
            lines.append("*Low confidence: rests on one outlet or a social post. Check before using.*")
    lines += ["", "_" + " · ".join(s["reasons"]) + "_", ""]
    links = []
    for a in s["articles"][:8]:
        links.append(f"[{a['outlet']}]({a['url']})")
        if a.get("discussion_url"):
            links.append(f"[discussion]({a['discussion_url']})")
    lines += ["Sources: " + " · ".join(links), ""]
    return lines


def history(page: dict, n: int = 5) -> list[str]:
    """The best-known items of the On this day page, newest year first."""
    items = sorted(sorted(page.get("items", []), key=lambda c: -c.get("score", 0))[:n], key=lambda c: -c["year"])
    if not items:
        return []
    out = [f"## On this day in Nepal: {page['label']}", ""]
    k = page.get("kantipur")
    if k:
        title = re.sub(r"^\[(Archive|अर्काइभ)\]\s*(\.\.\.)?", "", k.get("title_en") or k["title"])
        out += ["Kantipur's archive pick" + (f" ({k['year']})" if k.get("year") else "")
                + f": [{title}]({k.get('url_en') or k['url']})", ""]
    for c in items:
        tag = {"birth": " (born)", "death": " (died)", "top_story": " (most covered that day)",
               "day_news": " (nepalnews.com that day)", "weekly": " (Nepali Times that week)"}.get(c["kind"], "")
        line = f"- **{c['year']}**{tag}: {c['sentence']}"
        if c.get("url") and c["kind"] != "top_story":
            line += f" [Wikipedia]({c['url']})"
        n = c.get("news")
        if n:
            when = "that week" if n.get("kind") == "nepalitimes" else "that day"
            line += f"\n  News {when}: [{n['outlet']}: {n['title']}]({n['url']}) ({n['date']})"
        out.append(line)
    return out + [""]


def digest(payload: dict, dashboard_url: str = "", top: int = 15, onthisday: dict | None = None) -> str:
    stories = payload["stories"]
    f = payload["funnel"]
    out = [f"# Nepal news radar, {payload['date']}", ""]
    out.append(f"{len(stories)} stories worth a look out of {f.get('stories', 0):,} found in "
               f"{f.get('articles_in_window', 0):,} articles from the last {payload.get('lookback_hours', 48)} hours. "
               f"{payload['new_today']} are new since yesterday.")
    if dashboard_url:
        out += ["", f"**[Open the dashboard]({dashboard_url})** for filters and the full list."]
    if payload.get("briefings"):
        out += ["", "Daily round-ups: " + " · ".join(f"[{b['title']}]({b['url']})" for b in payload["briefings"])]
    abroad = [s for s in stories if s.get("topic") == "Nepalis abroad & migration" or (s.get("brief") or {}).get("scope") == "diaspora"]
    out += ["", "## Top stories", ""]
    for i, s in enumerate(stories[:top], 1):
        out += _story(i, s)
    extra = [s for s in abroad if s not in stories[:top]][:5]
    if extra:
        out += ["## Also: Nepalis abroad", ""]
        for i, s in enumerate(extra, 1):
            out += _story(i, s)
    if onthisday:
        out += history(onthisday)
    bad = [s for s in payload["sources"] if not s["ok"] or "failed:" in (s.get("detail") or "")]
    if bad:
        out += ["## Source problems", ""] + [f"- **{s['name']}**: {s['error'] or s['detail']}" for s in bad] + [""]
    u = payload.get("llm", {})
    out.append("---")
    if u.get("enabled"):
        out.append(f"Briefs by {u['model']} from headlines and feed snippets only; each was checked against a "
                   f"verbatim quote ({u['unverified']} discarded). Cost today ${u['cost_usd']:.4f}.")
    else:
        out.append("Briefs are off (set ANTHROPIC_API_KEY to turn them on). Headlines are the outlets' own.")
    return "\n".join(out) + "\n"
