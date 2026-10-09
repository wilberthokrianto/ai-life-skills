---
name: creator-digest
description: Scheduled YouTube digest. Reads a watchlist of channels, people, and topics from the vault, finds the new videos since the last run on its own (no pasted links), fetches transcripts with scripts, and writes a compact takeaway digest into the vault - with optional full /summarize notes for channels marked deep. Built to be cheap enough to run every few days. Use when the user wants to follow creators, run or set up the creator feed, or asks "what's new from the people I follow".
user_invocable: true
---

# Creator Digest

Turns `summarize` from "paste a link" into "tell me what I missed." Discovery and transcript fetching are **scripts that cost zero tokens**; the model only reads transcripts to write takeaways, and a hard per-run cap bounds the spend.

## Requirements

Same vault as `summarize`. Needs `yt-dlp` and `python3` (stdlib only). On first run, check `command -v yt-dlp python3` and ask before installing (`brew install yt-dlp` / `pip install yt-dlp`).

Runs best **locally** (a Mac that is on at the scheduled time): YouTube blocks most datacenter IPs and the `subscriptions` source needs your browser's logged-in cookies. A cloud schedule can work for public channels only, and may hit bot checks. If a cloud run reports `no_captions` for everything, that is why.

## Configuration

```
VAULT_ROOT   = $VAULT_ROOT        # resolve exactly as summarize Step 0a
FEED_NOTE    = 01 Updates/📺 Creator Feed.md     # watchlist + digest live here
STATE_FILE   = 01 Updates/.creator-feed-state.json   # dotfile: seen ids, backlog, last_run
SCRIPTS      = <this skill dir>/scripts
SCRATCH      = a fresh temp dir for transcripts (deleted at the end)
```

If `FEED_NOTE` is missing, copy `vault/01 Updates/📺 Creator Feed.md` from the repo into the vault and ask the user to fill in the watchlist (or offer to build it from what they tell you: names, channels, topics). Never run with an empty watchlist.

## Inputs

Optional, from the invocation: `--max N` (override `max_videos`), `--lookback N` (days), `dry-run` (steps 1-2 only, report what *would* be summarized), `deep <id|title>` (promote one already-digested video to a full note, see Step 5). Scheduled runs must never prompt interactively.

## Step 1: Discover (script, no tokens)

```bash
python3 "$SCRIPTS/discover.py" find --watchlist "$VAULT_ROOT/$FEED_NOTE" --state "$VAULT_ROOT/$STATE_FILE"
```

`start_date` in the watchlist is a floor: nothing uploaded before it is ever picked up. A channel written as a plain name (with spaces) is resolved by search, and `resolved_channels` in the output shows which channel it picked. On first run, show the user that mapping and confirm before summarizing.

Returns JSON: `process` (up to `max_videos` videos), `backlog` (over the cap, carried to next run), `stats` (what the filters dropped), `since`.

What the script already did, so you do not redo it:
- Channels via free RSS (id cached after first lookup), people/topics via date-sorted search
- Dropped: already seen, older than the window, Shorts / too short, too long (unless `long`), live/upcoming, and search hits that do not actually name the person or all topic words
- Ranked: `deep` channels first, then explicit channels/subscriptions, then search hits, newest first

If `process` is empty, write nothing to the feed, report "nothing new" with the `stats`, run `finish` (Step 6), and stop. Quiet days must cost almost nothing.

## Step 2: Report the plan

One short line to the user (or the run log when scheduled): `N new videos (M deep), K in backlog, dropped: <stats>`. With `dry-run`, list titles and stop here.

## Step 3: Fetch transcripts (script, no tokens)

For each video in `process`, in parallel (Bash background jobs or one loop):

```bash
python3 "$SCRIPTS/transcript.py" <id> --out "$SCRATCH" --browser "<settings.browser>"
```

- Result `error: no_captions` -> **skip, do not transcribe audio** in a scheduled run (that is the expensive path). Mark `skipped`, list it in the digest as a title-only line with `[Watch](url)` so nothing silently disappears. Offer `/summarize <url>` for it interactively.
- Manual captions beat auto captions (the script already picks them).

## Step 4: Summarize (the only token spend)

**Never paste a transcript into the main conversation.** Dispatch one **Sonnet** subagent per video, in parallel, passing only the transcript *file path*, title, channel, duration, and the instructions below. The subagent returns text only. Never Haiku (same rule as `summarize`).

Subagent instructions:

> Read the transcript at `<path>`. Return, in this exact shape and nothing else:
> `TLDR:` one sentence on the video's actual claim, not its topic.
> `POINTS:` N bullets, each one concrete (a claim, number, mechanism, or decision, with the `[M:SS]` it comes from). No filler like "they discuss…".
> `QUOTE:` optional, one line worth keeping, with speaker and `[M:SS]`.
> `THEME:` 2-4 words.
> Wikilink only people and named things that are central; do not wikilink generic terms.

N by duration: under 20 min = 3, 20-60 min = 4, over 60 min = 5. Transcripts over ~40k words: the subagent reads in chunks and merges; do not fan out into more agents.

This is intentionally **not** the full `summarize` pipeline: no section-by-section pass, no reference notes, no Bases updates, no per-video note. That is what keeps a 6-video run at roughly the cost of 6 minimal summaries' *first pass* instead of 6 full vault expansions.

## Step 5: Deep videos

For videos from a `| deep` source (or one the user promotes with `deep <id>`), after Step 4 run the real skill in **minimal** mode on the URL so the full note, transcript note, and creator person note are created exactly as usual:

`/summarize <url> minimal`

Pass `minimal` explicitly so a scheduled run never blocks on the depth prompt. Link the resulting note from the digest entry.

Promotion is the escape hatch for the cheap default: the user reads the digest, sees one video worth keeping, says `deep <title>`, and only then pays for the full note.

## Step 6: Write the digest

Edit `FEED_NOTE` following the format in its own prompt callout (that callout is the source of truth; if it differs from below, follow it):

- New run goes at the top, after the prompt and watchlist, under `## YYYY-MM`, heading `### [[MM-DD-YY ddd]]`
- Collapse the previous run into a `> [!note]- [[date]]` callout (prefix its lines with `> `)
- `> [!tldr]` first: "N videos from X, Y, Z. Common thread: …" Only if there really is one.
- One collapsed `> [!note]-` per video, titled `Channel: Title (47m)`; body is the subagent's TLDR, POINTS, QUOTE, then `[Watch](url)` and, if deep, the `[[full note]]`
- Skipped (no captions) and backlog entries as a final plain list of titles + links
- Set `unread: true`, update `updated:`
- No `# Title` heading, per vault rules

Then update state and the daily note:

```bash
python3 "$SCRIPTS/discover.py" mark --state "$VAULT_ROOT/$STATE_FILE" --status done <ids...>
python3 "$SCRIPTS/discover.py" mark --state "$VAULT_ROOT/$STATE_FILE" --status skipped <ids...>
python3 "$SCRIPTS/discover.py" finish --state "$VAULT_ROOT/$STATE_FILE"
```

Only `mark` videos that actually made it into the digest, so a failed run retries them. Then add to the daily note (summarize Step 7 format):

```markdown
## creator digest
- [[📺 Creator Feed]] — N videos: <theme list>
```

Delete `SCRATCH`.

## Cost controls (why this is cheap)

| Lever | Effect |
|---|---|
| Discovery + transcripts are scripts | 0 tokens until a transcript is actually worth reading |
| `max_videos` cap + backlog | Hard ceiling per run; overflow waits instead of spiking |
| `min_minutes` / `max_minutes` | Drops Shorts and 8-hour streams before anything is read |
| Person/topic hits must literally match | Search noise dies in the script |
| Seen-state | A video is never summarized twice, even if it surfaces from two sources |
| Transcript by file path, one Sonnet per video | Main context never holds transcripts; no Opus |
| Digest-only by default, `deep` opt-in | Full notes only for what you chose |
| No audio transcription when scheduled | The expensive fallback never runs unattended |
| Empty run = no writes | Quiet days cost ~nothing |

Tuning: if spend is still too high, lower `max_videos`, set `per_source` to 5, drop `topic:` lines (the noisiest), or move channels off `deep`.

## Key rules

1. Never prompt in a scheduled run; every choice comes from the watchlist or flags
2. Scripts find and fetch; the model only reads transcripts to write takeaways
3. Never put a transcript in the main context
4. Never Haiku. Sonnet for digest entries, `summarize minimal` for deep
5. Only `mark` what landed in the digest
6. No `# Title` headings; `unread: true` on every note touched
7. Never skip silently: no-captions and backlog videos are listed by title
