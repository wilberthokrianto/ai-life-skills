---
name: creator-digest
description: Scheduled YouTube feed. Reads a watchlist of channels, people, and topics from the vault, finds the new videos since the last run on its own (no pasted links), fetches transcripts with scripts, and has one Sonnet worker per video write a full summary note (summarize minimal format) - then links them from the feed note, a per-creator hub, and the daily note. Use when the user wants to follow creators, run or set up the creator feed, or asks "what's new from the people I follow".
user_invocable: true
---

# Creator Digest

Turns `summarize` from "paste a link" into "tell me what I missed." Two tiers:

- **Orchestrator (this conversation):** runs scripts, reads their short output lines, dispatches workers, and makes small edits (feed note, hub notes, daily note). It **never reads a transcript or a finished note**.
- **Worker (one Sonnet subagent per video):** reads the transcript itself, writes the whole summary note, verifies it with a script, and reports one line.

Discovery, transcripts, planning, and verification are **scripts that cost zero tokens** and print only short lines (paths, counts, problems), never content.

## Requirements

Same vault as `summarize`. Needs `yt-dlp` and `python3` (stdlib only). On first run, check `command -v yt-dlp python3` and ask before installing (`brew install yt-dlp` / `pip install yt-dlp`).

Runs best **locally** (a Mac that is on at the scheduled time): YouTube blocks most datacenter IPs and the `subscriptions` source needs your browser's logged-in cookies. A cloud schedule can work for public channels only, and may hit bot checks. If a cloud run reports `no_captions` for everything, that is why.

## Configuration

```
VAULT_ROOT   = $VAULT_ROOT        # resolve exactly as summarize Step 0a
FEED_NOTE    = 01 Updates/📺 Creator Feed.md     # watchlist + feed live here
STATE_FILE   = 01 Updates/.creator-feed-state.json   # dotfile: seen ids, backlog, last_run
SCRIPTS      = <this skill dir>/scripts
SCRATCH      = a fresh temp dir for transcripts (deleted at the end)
```

If `FEED_NOTE` is missing, copy `vault/01 Updates/📺 Creator Feed.md` from the repo into the vault and ask the user to fill in the watchlist (or offer to build it from what they tell you: names, channels, topics). Never run with an empty watchlist.

## Inputs

Optional, from the invocation: `--max N` (override `max_videos`), `--lookback N` (days), `dry-run` (steps 1-2 only, report what *would* be summarized). Scheduled runs must never prompt interactively.

## Step 1: Discover (script)

```bash
python3 "$SCRIPTS/discover.py" find --watchlist "$VAULT_ROOT/$FEED_NOTE" --state "$VAULT_ROOT/$STATE_FILE" > "$SCRATCH/find.json"
```

`start_date` in the watchlist is a floor: nothing uploaded before it is ever picked up. A channel written as a plain name (with spaces) is resolved by search, and `resolved_channels` in the output shows which channel it picked. On first run, show the user that mapping and confirm before summarizing.

Returns JSON: `process` (up to `max_videos` videos), `backlog` (over the cap, carried to next run), `stats` (what the filters dropped), `since`, `settings`. Read only the fields you need (ids, titles, stats) with a one-line `python3 -c`, not the whole file.

What the script already did, so you do not redo it:
- Channels via free RSS (id cached after first lookup), people/topics via the upload-date-sorted results page
- Dropped: already seen, older than the window, Shorts / too short, too long (unless `long`), live/upcoming, and search hits that do not actually name the person or all topic words
- Ranked: explicit channels/subscriptions first, then search hits, newest first
- Remembered: every person/topic hit that passed the filters is saved in the state backlog until it is marked or 14 days old, because the same search may not return it next time

If `process` is empty, write nothing to the feed, report "nothing new" with the `stats`, run `finish` (Step 7), and stop. Quiet days must cost almost nothing.

## Step 2: Report the plan

One short line to the user (or the run log when scheduled): `N new videos, K in backlog, dropped: <stats>`. With `dry-run`, list titles and stop here.

## Step 3: Fetch transcripts (script)

All videos in parallel, one JSON line each, collected into one file:

```bash
for id in <ids>; do python3 "$SCRIPTS/transcript.py" "$id" --out "$SCRATCH" --lang "<settings.lang>" --browser "<settings.browser>" & done > "$SCRATCH/transcripts.jsonl"; wait
```

Caption language follows `lang` in the watchlist (default `en, id`): uploaded captions in that order, then the video's original-language auto captions, then auto (possibly machine-translated) ones. `error: no_captions` -> **do not transcribe audio** in a scheduled run (that is the expensive path); the video is listed by title in the feed (Step 6) and marked `skipped`. Interactively, offer `/summarize <url>` for it.

## Step 4: Plan (script)

```bash
python3 "$SCRIPTS/plan.py" plan --find "$SCRATCH/find.json" --transcripts "$SCRATCH/transcripts.jsonl" --vault "$VAULT_ROOT"
```

Prints, per video, `VIDEO / META / TRANSCRIPT / WORDS / WRITE / OUTPUT / TARGET / STATUS` lines, then `COLLISION <person> <ids>` and `NO_TRANSCRIPT <id> <error>` lines. Everything the worker needs comes from these lines:

- `OUTPUT` is `08 Summaries/<Channel>/Summaries/<Title>.md` with `| # ^ [ ] : / \ ? " * < >` removed. The note's wikilink name is that filename without `.md`.
- `TARGET` is a formula on the transcript word count W:
  - summary words: 7% to 15% of W (never below 150; the max is capped at 3,000)
  - sections: ceil(W/2500) to ceil(W/1500), at least 1
  - tldr: 2 sentences if W < 5,000, 3 if W < 15,000, else 4

  For example, a 50-minute talk (~8,700 words) gets 611-1,310 words in 4-6 sections; a 2-hour podcast (~21,000 words) gets 1,467-3,000 in 9-14. `verify_note.py` allows 10% either side. The formula lives in `plan.py` (`target()`); `verify_note.py` imports it, so change it there only.

- `WRITE` is the note language: the transcript's language, unless the source has `| write=id` or `| write=en` in the watchlist.
- `STATUS exists` -> **skip** that video (already summarized); it still counts as done.
- `COLLISION` -> two or more videos in this batch share a creator or guest (guests are parsed from titles: "Ft. X", "feat. X", "... | X"). Warn the user in one line, and add the collision line to those workers' prompts (below). Every worker is append-only on existing person notes anyway.

## Step 5: Dispatch workers

One `general-purpose` subagent with **`model: "sonnet"`** per `STATUS new` video, **all in parallel, in one message**. Never a bigger model, never Haiku, never a per-section fan-out. Fill the template completely; the worker sees nothing else:

```
Write one Obsidian summary note for a YouTube video. Work only from files: read the
transcript yourself and write the note directly to the vault. NEVER paste the transcript
or the note into your reply.

SOURCE: <url>
METADATA: title "<title>" | channel "<channel>" | duration <duration> | views <views> | uploaded <YYYY-MM-DD>
TRANSCRIPT: <path> (<words> words, with [M:SS] / [H:MM:SS] markers about every 60s)
VAULT_ROOT: <path>
OUTPUT: <VAULT_ROOT>/<OUTPUT>   (create parent folders if needed)
NOTE NAME: <OUTPUT filename without .md>   (use this in [[links]] to the note)
TARGETS: <min>-<max> summary words, <a>-<b> sections, <n>-sentence tldr, MAX 10 wikilinks
LANGUAGE: write the note in <Indonesian|English>. Frontmatter keys stay in English.
VERIFY: python3 "<SCRIPTS>/verify_note.py" "<full OUTPUT path>" --source-words <words> --headline "<HEADLINE>"
<only if a COLLISION names this video: "Another worker is writing about <person> at the
same time: never create or rewrite their person note wholesale; append only.">

1. Read the transcript (in chunks if it is long).

   DEPTH: keep the concrete juice: arguments, numbers, names, stories, and the best quotes
   with their timestamps. Cut filler and repetition. Stay inside TARGETS.
   ACCURACY: auto-captions mishear. If a name, company or number is not clear in the
   captions, write it with (?) after it, e.g. "PT Bumi Resources (?)", or leave it out.
   Never guess, and never wikilink a (?) name.

2. Write the note at OUTPUT (summarize skill, MINIMAL mode):
   FRONTMATTER: created + updated (YYYY-MM-DDTHH:mm, now), date (= uploaded), summary
   (one line, <= 70 characters, in LANGUAGE), categories: ["[[posts.base]]"], unread: true,
   tags: [youtube], recording: "<url>", views, duration, uploaded, creator: "[[<channel>]]",
   people: [creators/guests only, as "[[Name]]"], guest: "[[Name]]" if there is one.
   BODY: a ```vid <url>``` block first, then a > [!tldr] callout (TARGETS sentences), then
   one ## section per topic in order, each heading ending with its [M:SS] start time,
   each section's length proportional to its share of the video. Put standout lines in
   > [!quote] callouts (speaker wikilink + timestamp; translate only if LANGUAGE differs
   from the speaker's). End with ## People Mentioned (one bullet per person: who they are).
   RULES: no "# Title" heading (the filename is the title); never repeat frontmatter facts
   in the body; wikilink only people and central named things (companies, products, books),
   at most 10 distinct links in the body; do not wikilink generic terms.

3. Person notes, for the creator and each guest only ("<VAULT_ROOT>/04 People/<Name>.md"):
   - Missing, and the name has 2+ words (e.g. "Boy Thohir", not "Juan"): create it from
     "<VAULT_ROOT>/_Templates/new person template.md" with the shell so you never
     overwrite one another worker just made:
       set -o noclobber; cat > "<person note>" <<'NOTE' ... NOTE
     Fill the bio from what the video says (no web research), unread: true, no "# " heading,
     and under ## updates one line linking [[<NOTE NAME>]]. If the create fails because the
     file now exists, treat it as existing. A one-word name: no person note and no wikilink,
     plain text only.
   - Existing: NEVER rewrite it. Only add one line under ## updates:
       - <uploaded YYYY-MM-DD from METADATA>: <one line> [[<NOTE NAME>]]
     (the video's UPLOAD date from METADATA, not today; same date in a new note's line)
     If ## updates is the last heading, append with: printf '%s\n' "<line>" >> "<person note>"
     Otherwise insert just that line with a single small edit right below "## updates".

4. Write your HEADLINE (English, one line, the video's actual claim, <= 160 characters).
   Run VERIFY with it. Fix every problem it prints (note or headline) and run it again,
   until it prints nothing.

5. Report back ONLY this one line:
   PATH=<OUTPUT path> WORDS=<n from: VERIFY command + --words> HEADLINE=<the verified headline>
```

If a worker reports problems it could not fix, run VERIFY yourself once to get the problem lines and report them; do not open the note.

## Step 6: Views (orchestrator, small edits only)

Use only the `PATH` / `WORDS` / `HEADLINE` lines and the `META` lines; never read the notes.

**Feed note** (`FEED_NOTE`), following the format in its own prompt callout (that callout is the source of truth; if it differs from below, follow it):

- New run goes at the top of the feed, after the prompt and watchlist, under `## YYYY-MM`, heading `### [[MM-DD-YY ddd]]`
- Collapse the previous run into a `> [!note]- [[date]]` callout (prefix its lines with `> `)
- One collapsed callout per video:
  ```
  > [!note]- <Channel>: <Title> (47m)
  > <HEADLINE>
  >
  > [[<NOTE NAME>]] · [Watch](<url>)
  ```
- No-caption and backlog videos as a final plain list of titles + `[Watch](url)`
- Set `unread: true`, update `updated:`. No `# Title` heading

**Creator hub** per video (creates `08 Summaries/<Channel>/<Channel>.md` if missing, newest first, skips duplicates):

```bash
python3 "$SCRIPTS/plan.py" hub --vault "$VAULT_ROOT" --channel "<channel>" --title "<title>" --date <uploaded> --headline "<HEADLINE>"
```

**Bases** (only if `$VAULT_ROOT/_Bases/posts.base` exists): for a creator new to the vault, add a named view to `posts.base` and embed it in their person note, exactly like summarize Step 6.

**Daily note** (`02 Daily/YYYY/MM/MM-DD-YY ddd.md`, create if needed with `unread: true`):

```markdown
## creator digest
- [[📺 Creator Feed]] — N notes: [[Note 1]], [[Note 2]], ...
```

## Step 7: State and cleanup

```bash
python3 "$SCRIPTS/discover.py" mark --state "$VAULT_ROOT/$STATE_FILE" --status done <ids...>
python3 "$SCRIPTS/discover.py" mark --state "$VAULT_ROOT/$STATE_FILE" --status skipped <ids...>
python3 "$SCRIPTS/discover.py" finish --state "$VAULT_ROOT/$STATE_FILE"
```

`done` = a note now exists for it (written this run, or `STATUS exists`). `skipped` = no captions. A worker that failed is **not** marked, so the next run retries it. Delete `SCRATCH`.

## Cost controls

| Lever | Effect |
|---|---|
| Discovery, transcripts, planning, verification are scripts | 0 tokens until a transcript is read by its worker |
| Orchestrator never reads transcripts or notes | Main context stays small however many videos run |
| One Sonnet worker per video, no fan-out | Cost scales with transcript length, nothing more |
| `max_videos` cap + backlog | **The main control**: each video is now a full note (a 2-hour podcast is a note of up to 3,000 words). Keep it at 3-4 for scheduled runs |
| `min_minutes` / `max_minutes` | Drops Shorts and 8-hour streams before anything is read |
| Seen-state + `STATUS exists` | A video is never summarized twice |
| No audio transcription when scheduled | The expensive fallback never runs unattended |
| Empty run = no writes | Quiet days cost ~nothing |

Tuning: lower `max_videos`, set `per_source` to 5, drop `topic:` lines (the noisiest), or lower `max_minutes` to skip long podcasts.

## Key rules

1. Never prompt in a scheduled run; every choice comes from the watchlist or flags
2. The orchestrator never reads a transcript or a finished note; scripts print only short lines
3. One Sonnet worker per video. Never Haiku, never a bigger model, never a per-section fan-out
4. Person notes: create if missing and the name has 2+ words (noclobber), otherwise append one line dated with the upload date
5. Only `mark` what has a note (done) or no captions (skipped)
6. No `# Title` headings; `unread: true` on every note touched
7. Never skip silently: no-caption and backlog videos are listed by title
