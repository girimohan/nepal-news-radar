# Nepal News Radar

Finds the news about Nepal and Nepali people that the most outlets are covering right now, in Nepali and
English, and keeps a searchable archive of past news going back years. Built on the
[viral-news-radar](https://github.com/girimohan/viral-news-radar) engine (collect, cluster, score, brief),
adapted for Nepali text and Nepal's news sites.

"Most covered" here means something you can measure: how many different outlets ran the story, how fresh it
is, whether more outlets picked it up since yesterday, and (when Reddit is set up) how much r/Nepal discussed it.

## What you get

| | |
|---|---|
| **Dashboard** | `docs/index.html`, served by GitHub Pages. **Today**: stories ranked 0-100, with topic filters, "Nepalis abroad", "in the international press" and "Nepali press only" views, and every outlet's own article. **Archive**: search past news by words (English or Nepali), dates, language and outlet, see articles per day, download a CSV. |
| **Daily digest** | The top 15 stories (plus stories about Nepalis abroad) arrive as a GitHub issue each morning, which GitHub emails to you. Also saved in `digests/latest.md`. |
| **Archive** | `docs/archive/YYYY/MM/DD.jsonl`, one file per day. Every run adds what it collected; the back-fill command adds any past day. |
| **On this day** | For today's date, the best-known Nepal incident of every past year since 1920, each with a news piece from that day: dashboard tab and a digest section. |
| **How it was built** | [`docs/progress.md`](docs/progress.md) (also on the Pages site as `progress.html`): the steps, the sources that worked and the ones that did not. Notes for Claude Code in [`CLAUDE.md`](CLAUDE.md). |
| **English briefs** (optional) | Claude reads the headlines and snippets of the top 30 stories, most of them in Nepali, and writes an English headline, summary, why it matters and an angle. |

## Sources

**Fresh news, three times a day**

- **28 Nepali news sites** through their RSS feeds. In English: The Kathmandu Post, The Himalayan Times,
  Onlinekhabar English, Nepali Times, Khabarhub English, Ratopati English, The Rising Nepal, The Annapurna
  Express, Nepal News English, Mirmire Online, Kathmandu Tribune. In Nepali: Onlinekhabar, BBC Nepali, Setopati,
  Nagarik, Ratopati, Annapurna Post, Gorkhapatra, Khabarhub, Himal Khabar, Baahrakhari, Ujyaalo, Nepal Press,
  Desh Sanchar, Nepal News, News of Nepal, Imagekhabar, Clickmandu.
- **Daily round-ups**: the newest Nepal News Evening Briefing (about 30 stories of the day in 50 words each) is
  linked at the top of the dashboard and the digest. Round-ups are kept out of the story list.
- **International outlets**, keeping only their items that mention Nepal: BBC Asia, Al Jazeera, The Diplomat,
  Hindustan Times.
- **GDELT** (free, no key), which indexes the world's news sites. It finds Indian, Bangladeshi, Malaysian, Gulf
  and Western coverage of Nepal that no Nepali feed shows.
- **Reddit** (optional): r/Nepal, r/NepalSocial, r/Kathmandu.

**Historic news**

- **GDELT**: the world's press about Nepal, any day since January 2017.
- **WordPress archives**: nine sites publish every article through a public API that can be asked for any
  date, which gives their complete output for any past day, back to their first post: Onlinekhabar (Nepali
  since 2013, English), Khabarhub (Nepali since 2018, English), News of Nepal (since 2015), Imagekhabar (since
  2016, 182,000 articles), Clickmandu (since 2016), Nepal News English (since November 2020) and Nepal News
  (Nepali, since May 2025).
- **For On this day** (below): Wikipedia's daily news pages (since about 2002), nepalnews.com's daily pages of
  2001-2004 as saved by the Internet Archive's Wayback Machine, the Nepali Times archive (every weekly issue
  since July 2000) and Kantipur's own daily "Kantipur Archive" reprint.

Checked 2026-11-25: Ekantipur, Republica, The Kathmandu Post and The Himalayan Times have no archive API or
dated site map (Republica's site map lists 50,000 links per file, without dates); Lokaantar, Ukaalo, Techpana
and ShareSansar have no working public feed; Desh Sanchar and Nepal Press block their archive API. Hamro
Patro's news section aggregates 100+ portals but has no public feed. Onlinekhabar English's "Daily Digest"
stopped on 1 October 2026. Google News is not used: its `robots.txt` disallows automated access.

Not online, for research by request: Press Council Nepal holds scanned dailies from 1974 to 2013 and weeklies
from 1974 to 2006; Madan Puraskar Pustakalaya and the US Center for Research Libraries hold microfilm and
scans of older Nepali papers; Archive Nepal (archivenepal.org, the new home of Digital Himalaya) has the Nepali
Times page scans and the Regmi Research Series.

## How it works

```
collect  ->  last 48 h  ->  drop noise and world pages  ->  archive  ->  cluster into stories  ->  match to earlier days  ->  score  ->  brief  ->  dashboard + digest
```

1. **Collect** (`nepalradar/sources/`). Feeds that send broken XML (bare `&`, HTML entities, undeclared
   namespaces, as several Nepali sites do) are repaired, or read item by item as a last resort. Feeds without
   dates get one from the link (`/2026/11/25/`) or from when the radar first saw the item.
2. **Drop noise.** Horoscopes (राशिफल), gold-price tickers and photo galleries go, and so do the world-news
   pages Nepali papers run (`exclude_url`).
3. **Archive** (`nepalradar/archive.py`). Every remaining article is stored by day.
4. **Cluster** (`nepalradar/cluster.py`). Articles about the same event become one story, using shared links,
   shared rare words and shared names. Nepali text is handled: Devanagari words and digits are read, and the
   postpositions Nepali joins to nouns are stripped, so सरकारले, सरकारको and सरकार count as one word. On the
   first live run, 21 Nepali headlines from 12 outlets about the Supreme Court's ruling on the police chief
   became one story, while a different Supreme Court case the same day stayed separate.
5. **Match to earlier days**, then **score (0-100)**: coverage (distinct outlets, weighted), engagement and
   velocity, multiplied by freshness and topic weight. Each story's topic is the one it matches most strongly,
   in English or Nepali keywords.
6. **Brief** (`nepalradar/llm.py`, optional). Each brief must quote its evidence word for word from the
   headlines or snippets, in the original language, or it is discarded.

## On this day in Nepal

Every run also builds "On this day" for today's date (`nepalradar/onthisday.py`):

1. **What happened.** For each year from 1920, English Wikipedia is searched for the exact date in both
   spellings together with "Nepal", and the curated "<year> in Nepal" pages are read for that date. A hit
   counts only when the date sits in a sentence of the article's prose (not a reference) and that sentence or
   the article is about Nepal.
2. **The most famous one per year.** Ranked by how many Wikipedia language editions cover it (the 2015
   earthquake has 72, a district-level event one or two), preferring incidents reported in the article's
   opening, sentences that say what happened "on 9 November 1990", and events over births and deaths.
3. **The news piece of that day.** The article's own citations are read, and the news report dated that day
   (or up to three days later) that best matches the incident is chosen. For 1 June 2001 it is The New York
   Times' "Royal Family of Nepal Is Shot Dead in Palace"; for 9 November 1990, "Nepal's King Gives Way to
   Multiparty Democracy". From 2013 the Nepali sites' archives are searched when no citation fits.
   Wikipedia's daily news pages ("Portal:Current events/2008 May 28", since about 2002) add incidents, each
   with the report it cites. Where no citation fits, the news piece comes from nepalnews.com's own page of that
   day (2001-2004, saved by the Wayback Machine), the Nepali sites' archives (2013 on) or that week's Nepali
   Times issue (2000 on).
4. **Years with nothing on Wikipedia** show nepalnews.com's lead story that day (2001-2004), the story most
   Nepali outlets ran that day (2014 on, found by running the radar's own clustering over that day's archive)
   or the Nepali Times headline of that week (2000 on).
5. **Kantipur's archive pick.** Kantipur reprints one of its own stories from about 26 years ago each day; the
   day's reprint is shown on top, with its year worked out from the Bikram Sambat dates in the story.

A date takes a few minutes to compute (a few hundred polite Wikipedia requests), so it is cached in
`data/onthisday/MM-DD.json` and reused for 60 days. `python -m nepalradar onthisday --date 06-01` shows any
date in the terminal.

## Set up (once)

1. **Create the repository** `nepal-news-radar` on GitHub and push this folder to it.
2. **Run it:** Actions -> *Nepal news radar* -> *Run workflow*. After that it runs by itself at 06:15, 13:00
   and 19:00 Nepal time.
3. **Turn on the dashboard:** Settings -> Pages -> *Deploy from a branch* -> `main`, folder `/docs`.
4. **Get the digest by email:** Watch -> All activity.
5. **Fill the archive:** Actions -> *Back-fill archive* -> enter a date range (up to about 6 months per run).

```bash
cd nepal-news-radar
git init && git add . && git commit -m "Nepal news radar"
git branch -M main
git remote add origin https://github.com/<your-user>/nepal-news-radar.git
git push -u origin main
```

### Optional: briefs and Reddit

- **Briefs:** add a repository secret `ANTHROPIC_API_KEY` (the same key as your other radars works).
- **Reddit:** create a "script" app at reddit.com/prefs/apps and add `REDDIT_CLIENT_ID` and
  `REDDIT_CLIENT_SECRET`. Without them the Reddit source is skipped.

## Run locally

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m nepalradar run                          # full run, about a minute
python -m nepalradar run --sources feeds          # Nepali portals only
python -m nepalradar archive backfill --from 2025-04-01 --to 2025-04-30
python -m nepalradar archive backfill --from 2015-04-25 --to 2015-05-31 --sources wordpress --query भूकम्प
python -m nepalradar archive search earthquake भूकम्प --from 2025-01-01 --to 2025-12-31
python -m nepalradar archive search "nepali workers" malaysia --all --lang en --json hits.json
python -m nepalradar archive stats
python -m nepalradar onthisday                    # today's date in Nepal's history
python -m nepalradar onthisday --date 04-25 --write
python -m http.server -d docs                     # dashboard at http://localhost:8000
```

## Change what it looks for

Everything is in `config.yaml`: `topics` (English and Nepali keywords, with weights), `feeds` (add any RSS
feed; `require_any` keeps only Nepal items from a general outlet; `undated: first_seen` for feeds without
dates), `sources.gdelt.queries` and `languages`, `archive.wordpress` (any WordPress news site:
`https://site/wp-json/wp/v2/posts` must answer), `exclude_title`, `exclude_url`, scoring and clustering.

## Limits

- Nepali- and English-language coverage of the same event are separate stories, because the words differ.
  The "Nepali press only" filter shows stories that have not reached English outlets yet.
- Nepali has no capital letters, so the "different names, different stories" check that guards English
  headlines cannot help with Nepali ones; Nepali stories rely on shared rare words alone.
- A general topic word can match world news that a Nepali portal files without a "world" section in its link.
- GDELT allows one request every 5 seconds and refuses everything for several minutes after a breach. The
  daily run makes one request; back-fills wait between days. It returns titles only, no snippets.
- The archive is only as complete as its sources: complete for the five WordPress sites, GDELT's sample for
  the world press, and from the first run onward for every other feed.
- Briefs are written from headlines and snippets, not full articles. Read the source before you publish.
- On this day finds what English Wikipedia records with an exact date. Many years have nothing for a given
  date, events before about 1950 are thin, and Nepali-calendar (Bikram Sambat) anniversaries are not matched.
  Old news pieces are the outlets' own pages, so some links behind paywalls or long gone may fail.
- The Wayback Machine saved most, not all, of nepalnews.com's 2001-2004 pages, and its 2004 stories carry no
  dateline, so they are dated by the page's file name. A Nepali Times item is that week's paper, not that day's.
- Kantipur's listing holds only about the last month of reprints, so its pick appears for recent dates only.

## Good citizenship

Only public feeds and documented APIs. The collector identifies itself, runs three times a day, uses 8
concurrent requests for feeds, pauses between archive pages, and backs off when rate-limited. Every story and
archive entry links to the outlet's own article; only headlines and short snippets are stored or shown.
