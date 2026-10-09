---
created:
updated:
topic: creator feed
frequency: every 3 days
ongoing: false
unread: false
---

> [!prompt]- Agent Instructions
> A scheduled digest of new videos from the people, channels, and topics you follow. Run it with the `creator-digest` skill:
>
> `/creator-digest` — or on a schedule, see the README ("Scheduling the creator digest").
>
> **Edit the watchlist below** (plain text, one source per line). Nothing else needs to change.
>
> | Line | Meaning |
> |---|---|
> | `channel: @handle` | Every new upload from that channel. Also accepts a channel URL or `UC…` id. |
> | `channel: @handle \| deep` | Same, but each video also gets a full `/summarize` note (minimal mode). Use for the few channels you want to absorb fully. |
> | `channel: @handle \| long` | Allow videos longer than `max_minutes` (multi-hour podcasts). |
> | `person: Full Name` | Any new video whose title/channel/description names them (guest appearances, interviews). |
> | `topic: some keywords` | Any new video containing all the words. Noisy — add `\| min_views=20000`. |
> | `subscriptions: true` | Everything in your real YouTube subscriptions feed. Needs `browser:` set (logged-in cookies). |
>
> **Settings** (same block): `lookback_days` (first run window), `max_videos` (hard cap per run — the main token control), `min_minutes` / `max_minutes` (duration filter, drops Shorts and 8-hour streams), `browser` (e.g. `chrome`), `per_source` (how many recent videos to check per source).
>
> **Output format** — newest run at the top, older runs collapsed, same convention as the other `01 Updates/` notes:
> - Run heading: `### [[MM-DD-YY Day]]`
> - One collapsed callout per video: `> [!note]- Channel: Title (47m)`
> - Body: 3–5 takeaway bullets, then `[Watch](url)`; deep videos also link `[[Full summary note]]`
> - Top of each run: one `> [!tldr]` line saying how many videos and the 1–2 themes across them
> - Group runs under `## YYYY-MM`; set `unread: true` and update `updated:` when adding entries

```watchlist
# lookback_days: 3
# max_videos: 6
# min_minutes: 8
# max_minutes: 240
# browser: chrome
# per_source: 10

# channel: @lexfridman | deep
# channel: @AndrejKarpathy
# person: Sam Altman
# topic: AI agents | min_views=20000
# subscriptions: true
```
