---
created:
updated:
topic: creator feed
frequency: every 3 days
ongoing: false
unread: false
---

> [!prompt]- Agent Instructions
> A scheduled feed of new videos from the people, channels, and topics you follow. Each video gets a full summary note in `08 Summaries/<Channel>/Summaries/`, linked from here and from the channel's hub note. Run it with the `creator-digest` skill:
>
> `/creator-digest` — or on a schedule, see the README ("Scheduling the creator digest").
>
> **Edit the watchlist below** (plain text, one source per line). Nothing else needs to change.
>
> | Line | Meaning |
> |---|---|
> | `channel: @handle` | Every new upload from that channel. Also accepts a channel URL or `UC…` id. |
> | `channel: @handle \| write=id` | Write that source's notes in Indonesian (`id`) or English (`en`) whatever the transcript language. |
> | `channel: @handle \| long` | Allow videos longer than `max_minutes` (multi-hour podcasts). |
> | `person: Full Name` | Any new video whose title/channel/description names them (guest appearances, interviews). |
> | `topic: some keywords` | Any new video containing all the words. Noisy — add `\| min_views=20000`. |
> | `subscriptions: true` | Everything in your real YouTube subscriptions feed. Needs `browser:` set (logged-in cookies). |
>
> **Settings** (same block): `lookback_days` (first run window), `max_videos` (hard cap per run — the main token control), `min_minutes` / `max_minutes` (duration filter, drops Shorts and 8-hour streams), `browser` (e.g. `chrome`), `per_source` (how many recent videos to check per source), `start_date` (YYYY-MM-DD floor: older uploads are never summarized), `lang` (caption languages to try, in order; default `en, id`). Notes are written in the transcript's language unless a source says `| write=`.
>
> **Output format** — newest run at the top, older runs collapsed, same convention as the other `01 Updates/` notes:
> - Run heading: `### [[MM-DD-YY Day]]`
> - One collapsed callout per video: `> [!note]- Channel: Title (47m)`
> - Body: one headline line (English), then `[[Summary note]] · [Watch](url)`
> - No-caption and backlog videos: a plain list of titles + `[Watch](url)` at the end of the run
> - Group runs under `## YYYY-MM`; set `unread: true` and update `updated:` when adding entries

```watchlist
start_date: 2026-10-09
max_videos: 6
min_minutes: 8
max_minutes: 240
per_source: 10
lang: en, id
# browser: chrome

channel: Raymond Chin
channel: @DiaryOfACEO
channel: I Will Teach You To Be Rich
channel: Leon Hartono

person: Bevan Pramudito
person: Mohnish Pabrai
person: Guy Spier
person: Morgan Housel
person: Naval Ravikant
```
