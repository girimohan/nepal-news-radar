# Nepal news radar: notes for Claude

Nepal's most covered news (Nepali and English portals), a day-by-day archive, and "On this day in Nepal".
Forked from the viral-news-radar engine. History of decisions and dead ends: `docs/progress.md`. Read it before
adding a source: many portals were already tried.

## Commands

```bash
pip install -r requirements-dev.txt
python -m pytest -q                              # offline; must stay green (CI runs it before every radar run)
python -m nepalradar run --sources feeds         # quick run without GDELT/Reddit
python -m nepalradar run                         # full run (GDELT is slow and rate-limited)
python -m nepalradar onthisday --date 06-01      # one date's history page (about 5 min, cached 60 days)
python -m nepalradar archive backfill --from 2025-04-01 --to 2025-04-30 --sources wordpress
python -m nepalradar archive search भूकम्प earthquake --from 2015-04-25 --to 2015-05-31
python -m http.server -d docs                    # dashboard
```

## Layout

- `nepalradar/pipeline.py`: collect, prefilter, archive, cluster, ledger, score, brief, `docs/news.json`
- `nepalradar/text.py`: Devanagari handling (stemming of joined postpositions, keyword boundaries)
- `nepalradar/sources/`: `feeds.py` (broken-XML repair), `gdelt.py`, `wordpress.py`, `reddit.py`
- `nepalradar/archive.py`: `docs/archive/YYYY/MM/DD.jsonl` + `index.json`
- `nepalradar/onthisday.py`: Wikipedia incidents, ranking, news piece; `history_sources.py`: Wikipedia daily news
  pages, nepalnews.com via Wayback (2001-2004), Nepali Times issues, Kantipur Archive, daily briefings
- `docs/index.html`: the whole dashboard (no build step); `config.yaml`: feeds, topics, archives, settings
- `.github/workflows/daily.yml` (3 runs a day, commits results, opens the digest issue), `backfill.yml`

## Rules

- Everything source-specific goes in `config.yaml`, not code.
- Be polite: identify with `http.USER_AGENT`, GDELT one request per 5 s, Wikipedia `maxlag`, short pauses for
  the Wayback Machine. Respect `robots.txt` (Google News is out for that reason).
- Tests never touch the network: monkeypatch `get`/`fetch` functions.
- Store and show only headlines and short snippets, always linking to the outlet.
- Writing patch scripts through shell heredocs mangled backslashes (`\b`, `\1`) more than once: write scripts or
  use the Edit tool instead, and check new regexes for control characters.
