from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import yaml

from . import pipeline, report

ROOT = Path(__file__).resolve().parent.parent


def cmd_run(args) -> int:
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    only = set(args.sources.split(",")) if args.sources else None
    try:
        payload = pipeline.run(cfg, Path(args.out), only=only, ledger_path=ROOT / "data" / "seen.json",
                               archive_root=None if args.no_archive else Path(args.archive))
    except RuntimeError as e:
        print(e, file=sys.stderr)  # nothing is overwritten when every source is down
        return 1
    if cfg.get("briefings"):
        from . import history_sources
        try:  # the outlets' own round-ups of the day, linked on the dashboard and in the digest
            payload["briefings"] = history_sources.latest_briefings(cfg)
            Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            print(f"Briefings failed: {type(e).__name__}: {e}", file=sys.stderr)
    page = None
    if cfg.get("onthisday", {}).get("enabled", True) and not args.no_history:
        from . import onthisday
        try:
            page = onthisday.for_date(cfg, onthisday.nepal_today(), ROOT / "data" / "onthisday")
            write_onthisday(page, Path(args.out).parent / "onthisday.json")
        except Exception as e:  # history is a bonus: never lose the day's radar over it
            print(f"On this day failed: {type(e).__name__}: {e}", file=sys.stderr)
    text = report.digest(payload, args.dashboard_url, onthisday=page)
    d = Path(args.digest)
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text(text, encoding="utf-8")

    f = payload["funnel"]
    print(f"collected {f['collected']:,} articles -> {f['articles_in_window']:,} in window -> {f['stories']:,} stories "
          f"-> {f['shown']} shown (new today: {payload['new_today']}); {f.get('archived_new', 0):,} added to the archive")
    for s in payload["sources"]:
        print(f"  {s['name']:11} {'ok ' if s['ok'] else 'ERR'} fetched {s['fetched']:>5,} in stories {s['in_stories']:>3}  {s['error'] or s['detail']}")
    u = payload.get("llm", {})
    if u.get("enabled"):
        print(f"  LLM {u['model']}: {u['calls']} new briefs, {u['cached']} cached, {u['failed']} failed, "
              f"{u['unverified']} discarded (quote not found), ${u['cost_usd']:.4f}")
    else:
        print("  LLM: off (set ANTHROPIC_API_KEY to turn on briefs)")
    for i, s in enumerate(payload["stories"][:10], 1):
        print(f"  {i:>2}. {s['score']:>5.1f}  {s['headline'][:90]}")
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as fh:
            fh.write(f"new_today={payload['new_today']}\nshown={f['shown']}\nfirst_run={'true' if payload['first_run'] else 'false'}\n")
    return 0


def write_onthisday(page: dict, path: Path) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(page, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_onthisday(args) -> int:
    from . import onthisday
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    oc = cfg.setdefault("onthisday", {})
    if args.from_year:
        oc["from_year"] = args.from_year
    if args.no_top_stories:
        oc["top_stories"] = False
    today = onthisday.nepal_today()
    if args.date:
        parts = [int(x) for x in args.date.split("-")]
        date = dt.date(today.year, parts[-2], parts[-1])
    else:
        date = today
    page = onthisday.for_date(cfg, date, ROOT / "data" / "onthisday", force=args.force)
    print(f"\nOn {page['label']} in Nepal ({len(page['items'])} years):")
    k = page.get("kantipur")
    if k:
        print("  Kantipur's archive pick" + (f" ({k['year']})" if k.get("year") else "") + f": {k.get('title_en') or k['title']}")
    for c in page["items"]:
        n = c.get("news") or {}
        tag = {"event": "", "birth": " [born]", "death": " [died]", "top_story": " [most covered that day]",
               "day_news": " [nepalnews.com that day]", "weekly": " [Nepali Times that week]"}.get(c["kind"], "")
        print(f"  {c['year']}{tag}  {c['sentence'][:150]}")
        if n:
            print(f"        news: {n['outlet']} ({n['date']}): {n['title'][:100]}")
    if date == today or args.write:
        write_onthisday(page, Path(args.out))
        print(f"written to {args.out}")
    return 0


def cmd_tune(args) -> int:
    """Score the clustering against hand-labelled headlines, at the configured settings and across a grid."""
    import itertools
    from . import cluster as clu
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")).get("clustering", {})
    arts, labels = clu.load_labelled(args.labels)
    cur = (cfg.get("threshold", 0.18), cfg.get("min_shared_terms", 1), cfg.get("dek_weight", 0.5), cfg.get("nameless_penalty", 0.1))
    m = clu.pair_scores(clu.cluster(arts, *cur), arts, labels)
    print(f"{len(arts)} labelled headlines, {len(set(labels))} stories")
    print(f"current settings {cur}: precision {m['precision']}, recall {m['recall']}, F1 {m['f1']}")
    rows = []
    for thr, ms, dw, pen in itertools.product([x / 100 for x in range(10, 42, 2)], (1, 2), (0, 0.5, 1.0), (0, 0.1, 0.2)):
        r = clu.pair_scores(clu.cluster(arts, thr, ms, dw, pen), arts, labels)
        rows.append((r["f1"], r["precision"], r["recall"], thr, ms, dw, pen))
    rows.sort(reverse=True)
    print("best on this set (f1, precision, recall, threshold, min_shared_terms, dek_weight, nameless_penalty):")
    for r in rows[:8]:
        print("  ", r)
    print("Precision matters more than recall here: a wrong merge makes a story look more viral than it is.")
    return 0


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def cmd_backfill(args) -> int:
    from . import archive
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    start, end = args.date_from, args.date_to or args.date_from
    if end < start:
        print("--to is before --from", file=sys.stderr)
        return 2
    srcs = set(args.sources.split(","))
    print(f"Back-filling {start} .. {end} from {', '.join(sorted(srcs))}"
          + (f", only articles matching {args.query!r}" if args.query else "")
          + (" (GDELT allows one request every 5 s: about 6-12 s per day)" if "gdelt" in srcs else ""))
    n = archive.backfill(Path(args.archive), cfg, start, end, srcs, args.query)
    print(f"done: {n:,} new articles in the archive")
    return 0


def cmd_search(args) -> int:
    from . import archive
    end = args.date_to or dt.date.today()
    start = args.date_from or end - dt.timedelta(days=30)
    rows = archive.search(Path(args.archive), args.words, start, end, outlet=args.outlet or "", lang=args.lang or "",
                          match="all" if args.all else "any")
    print(f"{len(rows):,} articles {start} .. {end}" + (f" matching {' + '.join(args.words) if args.all else ' / '.join(args.words)}" if args.words else ""))
    for r in rows[: args.limit]:
        print(f"  {r['published'][:10]}  {r['outlet'][:22]:22}  {r['title'][:100]}")
        print(f"              {r['url']}")
    if args.json:
        Path(args.json).write_text(__import__("json").dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"all {len(rows):,} written to {args.json}")
    return 0


def cmd_stats(args) -> int:
    from . import archive
    idx = archive.update_index(Path(args.archive))
    days = idx["days"]
    print(f"{idx['total']:,} articles on {len(days):,} days, {idx['first'] or '-'} .. {idx['last'] or '-'}")
    by_month: dict[str, int] = {}
    for d, v in days.items():
        by_month[d[:7]] = by_month.get(d[:7], 0) + v["n"]
    for m, n in sorted(by_month.items()):
        print(f"  {m}  {n:>7,}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nepalradar", description="Nepal news radar: today's most widely covered Nepal stories, and a searchable archive.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="collect, cluster, score -> docs/news.json + digests/latest.md")
    r.add_argument("--config", default=str(ROOT / "config.yaml"))
    r.add_argument("--out", default=str(ROOT / "docs" / "news.json"))
    r.add_argument("--digest", default=str(ROOT / "digests" / "latest.md"))
    r.add_argument("--sources", help="comma-separated subset: feeds,gdelt,reddit,hackernews")
    r.add_argument("--archive", default=str(ROOT / "docs" / "archive"))
    r.add_argument("--no-archive", action="store_true", help="do not add today's articles to the archive")
    r.add_argument("--no-history", action="store_true", help="skip the On this day page")
    r.add_argument("--dashboard-url", default=os.environ.get("DASHBOARD_URL", ""))
    r.set_defaults(fn=cmd_run)
    t = sub.add_parser("tune", help="check the story clustering against hand-labelled headlines")
    t.add_argument("--config", default=str(ROOT / "config.yaml"))
    t.add_argument("--labels", default=str(ROOT / "tests" / "fixtures" / "day.json"))
    t.set_defaults(fn=cmd_tune)
    o = sub.add_parser("onthisday", help="On this day in Nepal: the best-known incident of each past year on a date")
    o.add_argument("--date", help="MM-DD (default: today in Nepal)")
    o.add_argument("--from-year", type=int, help="first year to look at (default from config, 1920)")
    o.add_argument("--force", action="store_true", help="recompute even when cached")
    o.add_argument("--no-top-stories", action="store_true", help="skip the archive clustering for recent years")
    o.add_argument("--write", action="store_true", help="write docs/onthisday.json even for a date other than today")
    o.add_argument("--config", default=str(ROOT / "config.yaml"))
    o.add_argument("--out", default=str(ROOT / "docs" / "onthisday.json"))
    o.set_defaults(fn=cmd_onthisday)
    a = sub.add_parser("archive", help="historic news: back-fill past days, search, stats")
    asub = a.add_subparsers(dest="acmd", required=True)
    b = asub.add_parser("backfill", help="fetch past days from GDELT (since 2017) and the WordPress sites' archives")
    b.add_argument("--from", dest="date_from", type=_date, required=True, help="first day, YYYY-MM-DD")
    b.add_argument("--to", dest="date_to", type=_date, help="last day (default: same as --from)")
    b.add_argument("--sources", default="wordpress,gdelt", help="wordpress,gdelt or one of them")
    b.add_argument("--query", default="", help="only articles matching this (e.g. earthquake, or भूकम्प)")
    b.set_defaults(fn=cmd_backfill)
    s = asub.add_parser("search", help="search the archive")
    s.add_argument("words", nargs="*", help="words or phrases, English or Nepali; any of them matches (see --all)")
    s.add_argument("--from", dest="date_from", type=_date)
    s.add_argument("--to", dest="date_to", type=_date)
    s.add_argument("--all", action="store_true", help="every word must appear")
    s.add_argument("--outlet")
    s.add_argument("--lang", help="en or ne")
    s.add_argument("--limit", type=int, default=40)
    s.add_argument("--json", help="also write every match to this file")
    s.set_defaults(fn=cmd_search)
    st = asub.add_parser("stats", help="articles per month; rebuilds docs/archive/index.json")
    st.set_defaults(fn=cmd_stats)
    for x in (b, s, st):
        x.add_argument("--config", default=str(ROOT / "config.yaml"))
        x.add_argument("--archive", default=str(ROOT / "docs" / "archive"))
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
