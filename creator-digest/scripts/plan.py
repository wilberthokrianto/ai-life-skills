#!/usr/bin/env python3
"""Per-video work plan and hub-note updates. Zero LLM tokens; prints short lines only.

  plan.py plan --find FIND.json --transcripts RESULTS.jsonl --vault VAULT
      For every video in `process` with a transcript, prints a block:
        VIDEO <id>
        META <title> | <channel> | <duration> | <views> | <uploaded> | <url>
        TRANSCRIPT <path>
        WORDS <n>
        WRITE <lang>
        OUTPUT <vault-relative note path>
        TARGET words=<min>-<max> sections=<a>-<b> tldr=<n> links<=10
        STATUS new | exists
      then `COLLISION <person> <id> <id>...` for people shared by 2+ new videos,
      and `NO_TRANSCRIPT <id> <error>` for videos without captions.

  plan.py hub --vault VAULT --channel CH --title T --date YYYY-MM-DD --headline H
      Adds `- [[T]] - DATE - H` to 08 Summaries/<CH>/<CH>.md, newest first
      (creates the hub if missing; no-op if T is already listed). Prints HUB <path>.
"""
import argparse, json, re, sys
from datetime import date
from pathlib import Path

SUMMARIES_DIR = "08 Summaries"
PEOPLE_DIR = "04 People"
MAX_LINKS = 10
# (max source words, summary words, sections, tldr sentences): about a third of the transcript,
# ~3000 summary words per hour of video. The last tier also covers longer transcripts.
# verify_note.py imports these, so this is the one place to change them.
TIERS = [(1500, (300, 500), (2, 3), "2"),
         (5000, (700, 1600), (4, 6), "3"),
         (15000, (1800, 4500), (6, 12), "3-4"),
         (float("inf"), (5000, 8000), (12, 20), "4-5")]
FORBIDDEN = r'[|#^\[\]:/\\?"*<>]'


def sanitize(name):
    return re.sub(r"\s+", " ", re.sub(FORBIDDEN, "", name)).strip(" .")


def target(words):
    for limit, w, s, t in TIERS:
        if words < limit:
            return w, s, t


def mmss(sec):
    sec = int(sec or 0)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def guests(title):
    """Guest names from common title patterns: 'Ft. A & B', 'feat. A', '... | Name'."""
    names = []
    m = re.search(r"\b(?:ft|feat|featuring)\.?\s+(.+)$", title, re.I)
    if m:
        names += re.split(r"\s*(?:&|,|\band\b|\bdan\b)\s*", m.group(1))
    parts = title.split("|")
    if len(parts) > 1 and len(parts[-1].split()) <= 4:
        names.append(parts[-1])
    return [n.strip(" -!.") for n in names if n.strip(" -!.")]


def cmd_plan(a):
    vault = Path(a.vault)
    find = json.loads(Path(a.find).read_text(encoding="utf-8"))
    results = {}
    for line in Path(a.transcripts).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("{"):
            r = json.loads(line)
            results[r["id"]] = r
    people = {}  # person -> [ids]
    for v in find["process"]:
        r = results.get(v["id"])
        if not r or "error" in r:
            print(f"NO_TRANSCRIPT {v['id']} {r.get('error') if r else 'missing'}")
            continue
        words = r["words"]
        (wmin, wmax), (smin, smax), tldr = target(words)
        out = Path(SUMMARIES_DIR) / sanitize(v["channel"]) / "Summaries" / f"{sanitize(v['title'])}.md"
        exists = (vault / out).exists()
        print(f"VIDEO {v['id']}")
        print(f"META {v['title']} | {v['channel']} | {mmss(v['duration'])} | {v['views']} | {v['uploaded']} | {v['url']}")
        print(f"TRANSCRIPT {r['path']}")
        print(f"WORDS {words}")
        print(f"WRITE {v.get('write') or r.get('lang') or 'en'}")
        print(f"OUTPUT {out}")
        print(f"TARGET words={wmin}-{wmax} sections={smin}-{smax} tldr={tldr} links<={MAX_LINKS}")
        print(f"STATUS {'exists' if exists else 'new'}")
        if not exists:
            for p in {v["channel"], *guests(v["title"])}:
                people.setdefault(p, []).append(v["id"])
    for p, ids in sorted(people.items()):
        if len(ids) > 1:
            print(f"COLLISION {p} {' '.join(ids)}")


def cmd_hub(a):
    ch = sanitize(a.channel)
    hub = Path(a.vault) / SUMMARIES_DIR / ch / f"{ch}.md"
    title = sanitize(a.title)
    line = f"- [[{title}]] - {a.date} - {a.headline.strip()}"
    now = date.today().isoformat()
    if not hub.exists():
        hub.parent.mkdir(parents=True, exist_ok=True)
        hub.write_text(f"---\ncreated: {now}\nupdated: {now}\ncreator: \"[[{a.channel}]]\"\nunread: true\n---\n\n## videos\n",
                       encoding="utf-8")
    text = hub.read_text(encoding="utf-8")
    if f"[[{title}]]" in text:
        print(f"HUB {hub} (already listed)"); return
    lines = text.splitlines()
    entry = re.compile(r"^- \[\[.*?\]\] - (\d{4}-\d{2}-\d{2}) - ")
    idx = [i for i, l in enumerate(lines) if entry.match(l)]
    pos = next((i for i in idx if entry.match(lines[i]).group(1) < a.date), None)
    if pos is None and idx:  # older than everything listed
        pos = idx[-1] + 1
    if pos is None:  # first entry: right under ## videos (added if missing)
        heading = next((i for i, l in enumerate(lines) if l.strip() == "## videos"), None)
        if heading is None:
            lines += ["", "## videos"]; heading = len(lines) - 1
        pos = heading + 1
    lines.insert(pos, line)
    text = "\n".join(lines) + "\n"
    text = re.sub(r"^updated:.*$", f"updated: {now}", text, count=1, flags=re.M)
    text = re.sub(r"^unread:.*$", "unread: true", text, count=1, flags=re.M)
    hub.write_text(text, encoding="utf-8")
    print(f"HUB {hub}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("--find", required=True)
    p.add_argument("--transcripts", required=True); p.add_argument("--vault", required=True); p.set_defaults(fn=cmd_plan)
    h = sub.add_parser("hub"); h.add_argument("--vault", required=True); h.add_argument("--channel", required=True)
    h.add_argument("--title", required=True); h.add_argument("--date", required=True)
    h.add_argument("--headline", required=True); h.set_defaults(fn=cmd_hub)
    a = ap.parse_args()
    sys.exit(a.fn(a))
