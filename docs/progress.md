---
title: How the Nepal news radar was built
---

# How the Nepal news radar was built

A record of what was built, in what order, what was tried and what did or did not work. Written on
25 November 2026, when the project was created in one long working session. [Dashboard](./) ·
[Code and README](https://github.com/girimohan/nepal-news-radar)

## The idea

Take the [viral-news-radar](https://github.com/girimohan/viral-news-radar) engine (collect, cluster, score, brief)
and point it at Nepal: news about Nepal and Nepali people, from Nepali portals in Nepali and English, both fresh
(today's most covered stories) and historic (a searchable archive going back years). Then add "On this day in
Nepal": for today's date, the best-known incident of each past year with a news piece from that day.

## Progress, step by step

| # | Step | Result |
|---|------|--------|
| 1 | Cloned viral-news-radar into `nepalradar/`, kept its engine and tests (the original topics live on as a test fixture) | Engine unchanged, tests green |
| 2 | Taught the text code Nepali: Devanagari letters and digits, Nepali stopwords, stripping postpositions joined to nouns (सरकारले, सरकारको -> सरकार), keyword matches that do not hit longer words (कर must not match कर्णाली) | 21 Nepali headlines from 12 outlets about one Supreme Court ruling became one story |
| 3 | Found and tested Nepal's feeds: 25 Nepali portals, 4 international outlets filtered to Nepal | Several feeds were broken XML; see "Feeds" below |
| 4 | Added GDELT (the world's press about Nepal) | Works, with care; see "GDELT" below |
| 5 | Built the archive: one file per day in `docs/archive/`, fed by every run and by back-fills from GDELT and WordPress sites' own archives; search in the dashboard and the command line | 627 articles for two April 2025 days; 15 earthquake stories for 25 April 2015 |
| 6 | Topic choice by strongest match, generic words (Nepal, Rs, crore...) kept from merging unrelated stories | Sports no longer labelled Society |
| 7 | Built "On this day in Nepal" from Wikipedia (see below) | 19 years for 25 November; royal massacre, 1990 constitution and 2015 earthquake checked by hand |
| 8 | Researched other portals, archives and summaries (about 40 sites probed) | See "Sources: what we tried" |
| 9 | Added the useful ones: 4 more WordPress archives, 3 feeds, the Nepal News Evening Briefing, Wikipedia's daily news pages, nepalnews.com 2001-2004 via the Wayback Machine, the Nepali Times archive, Kantipur's daily archive reprint | 31 years for 25 November; 32/32 feeds read |
| 10 | Pushed to GitHub, dashboard on GitHub Pages, three runs a day by GitHub Actions | First run passed in 10 min, except GDELT |
| 11 | Looked into GDELT failing on GitHub (see "GDELT, the hard way") | Patient retries, and reuse of the last good fetch |

## Sources: what we tried

### Worked

| Source | What it gives | Notes |
|---|---|---|
| RSS feeds of 28 Nepali sites + 4 international | Fresh news | Broken XML repaired (bare `&`, HTML entities, undeclared namespaces, whitespace before the XML declaration), or read item by item; undated feeds dated from the link or from first sighting |
| WordPress API (`/wp-json/wp/v2/posts?after=&before=`) | Complete archive for any date | Onlinekhabar (2013 on), Khabarhub (2018), News of Nepal (2015), Imagekhabar (2016), Clickmandu (2016), Nepal News English (Nov 2020), Nepal News (May 2025) |
| GDELT DOC 2.0 | World press about Nepal, 2017 on | One request per 5 s; see below |
| Wikipedia search + "YYYY in Nepal" pages + Wikidata sitelinks | Dated incidents and how famous they are | Basis of On this day |
| Wikipedia's daily news pages (Portal:Current events/YYYY Month D) | Dated events with a cited report | From about 2002 (checked 2004 on; 1998-2001 pages do not exist) |
| Wayback Machine (CDX API) | nepalnews.com daily pages 2001-2004 | 1999-2000 not saved, 2005 on only pictures. 2001 pages have datelines, 2002-2003 a sign-off ("nepalnews.com am Jan 2"), 2004 nothing but the file name |
| archive.nepalitimes.com | Every weekly issue since #1 (19 July 2000) | Found by searching issue numbers by date; teasers from the page's structured data |
| ekantipur.com/Kantipur-Archive | One Kantipur story from about 26 years ago, reprinted each day | Started 20 October 2026; listing holds about a month; the year comes from the Bikram Sambat dates in the story |
| Nepal News Evening Briefing | Daily round-up of about 30 stories | Linked, not clustered |

### Did not work, or not usable

| Tried | What happened |
|---|---|
| Google News | `robots.txt` disallows automated access: not used |
| Ekantipur, Republica, Kathmandu Post, Himalayan Times archives | No archive API or dated site map (Republica's site map has 50,000 links per file, no dates) |
| Lokaantar, Ukaalo, Techpana, ShareSansar feeds | No working public feed at the time |
| Desh Sanchar, Nepal Press WordPress API | Blocked (403) |
| Hamro Patro news | Aggregates 100+ portals, but no public feed |
| Onlinekhabar English "Daily Digest" | Stopped on 1 October 2026; left switched off in the config |
| ReliefWeb API | v1 is shut down; v2 needs an approved app name (free, by request): not done yet |
| ACLED | Needs a free account key: not done yet |
| Press Council Nepal, Madan Puraskar Pustakalaya, CRL microfilm | Real pre-2000 newspapers (dailies 1974-2013), but offline or by request only |
| Archive Nepal / Digital Himalaya | Page scans of Nepali Times and the Regmi Research Series, no date search |
| Internet Archive search for Gorkhapatra | About 21 scattered items: too thin |

### GDELT, the hard way

- A long OR query of Nepali and English terms timed out. The default query is now just `nepal`.
- GDELT allows one request every 5 seconds and refuses everything for minutes after a breach. Requests are
  spaced from the end of the previous answer, with back-off of 30, 75 and 150 seconds.
- Splitting the day into dated windows was slow enough to fail the whole run. Now the fast `timespan` query runs
  first and the window is split only when it returns the full 250; if splitting fails, the first answer is kept.
- Day-by-day archive back-fills from GDELT timed out during testing and remain unverified.
- **On GitHub's runners every request was refused** (HTTP 429, first run and a one-day back-fill test). From a home
  connection, spaced requests were refused about half the time whatever the gap: a 30 s gap was refused, 45 s
  worked, 60 s was refused, 90 s worked. So this is GDELT shedding load, made worse by GitHub's shared IP
  addresses, not the radar asking too often.
- The fix (step 11): the daily run retries up to four times with waits of 45, 90 and 150 s (plus random jitter), and
  when GDELT still refuses, it reuses the articles of the last fetch that worked (`data/gdelt_last.json`) that are
  still inside the 48-hour window. The Sources tab and the digest say when that happens.

## On this day: what we tried

- **Finding incidents.** Wikipedia search for the exact date in both spellings plus "nepal", and the "YYYY in Nepal"
  pages. The date must sit in a prose sentence (not a reference, not "the Kathmandu Post on 25 November 2009"),
  starting with a capital, 40-600 characters.
- **Relevance.** At first any article mentioning Nepal counted, and a St Helena governor who once served in
  Kathmandu came up. Now the dated sentence itself, or the article's title or one-line description, must be about
  Nepal.
- **Ranking.** By Wikipedia language editions (sitelinks). "Flag of Nepal" (76 languages) beat the 1990
  constitution because it mentions the date in passing. Fixed by preferring dates in the article's opening, verbs
  of something happening, "on 9 November 1990", events over births and deaths, and items on the year page.
- **The news piece.** The article's own dated citations (same day to three days later). A constitution text site
  was picked once, so only news-like citations count.
- **Recent years.** From 2014, when Wikipedia has nothing, the day's articles from the WordPress archives are
  clustered and the story most outlets ran is shown. These headlines are in Nepali.
- **Checked by hand:** 1 June 2001 (royal massacre, NYT "Royal Family of Nepal Is Shot Dead in Palace"), 9 November
  1990 (constitution, NYT "Nepal's King Gives Way to Multiparty Democracy"), 25 April 2015 (earthquake, Telegraph),
  25 November (31 years). Other dates were only spot-checked.
- **Cost.** A few hundred polite Wikipedia requests, about five minutes per date, so each date is cached for 60
  days in `data/onthisday/`.

## Known limits

- Nepali and English coverage of the same event are separate stories.
- Bikram Sambat anniversaries (e.g. Mangsir 10) are not matched.
- 2015-2025 "most covered" items are in Nepali.
- Before about 1950, Wikipedia has little with exact dates.

## Ideas for later

- Match Bikram Sambat dates.
- An English line for Nepali top stories (Claude, when `ANTHROPIC_API_KEY` is set).
- Link Nepali and English coverage of one event.
- ReliefWeb (app name) and ACLED (key) for disasters and conflict events.
