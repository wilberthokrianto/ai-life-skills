#!/usr/bin/env python3
"""Deterministic checks for a creator-digest summary note. Prints only the problems
(one per line); prints nothing when the note passes.

  verify_note.py NOTE.md --source-words N [--headline TEXT] [--words]
  verify_note.py NOTE.md --min WORDS --max WORDS [--headline TEXT] [--words]

Target summary words come from the transcript word count (--source-words, same tiers as
plan.py), or are given directly with --min/--max. Word count = body words, excluding
frontmatter and fenced code blocks (the vid embed). Allowed range is the target range
widened to -25% / +35%.
--headline: also check the worker's report HEADLINE (<= 160 characters, one line).
--words: print only `WORDS <n>` (the body word count) and exit; for the worker's report.
"""
import argparse, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plan import target  # noqa: E402  (single source of truth for the length tiers)

REQUIRED = ["created", "updated", "date", "summary", "categories", "unread", "tags",
            "recording", "views", "duration", "uploaded", "creator", "people"]
NON_EMPTY = ["created", "updated", "date", "summary", "recording", "creator"]
FORBIDDEN = set('|#^[]:/\\?"*<>')
MAX_LINKS = 10
MAX_SUMMARY = 70
MAX_HEADLINE = 160


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("note"); ap.add_argument("--source-words", type=int)
    ap.add_argument("--min", type=int); ap.add_argument("--max", type=int)
    ap.add_argument("--headline"); ap.add_argument("--words", action="store_true")
    a = ap.parse_args()
    if a.source_words is not None:
        a.min, a.max = target(a.source_words)[0]
    if a.min is None or a.max is None:
        ap.error("give --source-words, or both --min and --max")
    path = Path(a.note)
    problems = []
    if not path.exists():
        print(f"missing file: {path}"); return 1
    bad = sorted(FORBIDDEN & set(path.stem))
    if bad:
        problems.append(f"filename has forbidden characters: {' '.join(bad)}")
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not m:
        print("no frontmatter block"); return 1
    fm_text, body = m.groups()
    fm = {}
    for line in fm_text.splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if km:
            fm[km.group(1)] = km.group(2).strip()
    for k in REQUIRED:
        if k not in fm:
            problems.append(f"frontmatter missing: {k}")
    for k in NON_EMPTY:
        if k in fm and fm[k] in ("", '""', "''"):
            problems.append(f"frontmatter empty: {k}")
    if fm.get("unread") not in (None, "true"):
        problems.append("frontmatter unread must be true")
    summary = fm.get("summary", "").strip().strip('"').strip("'")
    if len(summary) > MAX_SUMMARY:
        problems.append(f"summary is {len(summary)} chars (max {MAX_SUMMARY})")

    prose = re.sub(r"^(```|~~~).*?^\1[^\n]*$", "", body, flags=re.S | re.M)
    if re.search(r"^# ", prose, re.M):
        problems.append("has a '# ' H1 heading (filename is the title)")
    if not re.search(r"^>\s*\[!tldr\]", prose, re.M | re.I):
        problems.append("no > [!tldr] callout")
    links = {l.strip() for l in re.findall(r"\[\[([^\]|#]+)", prose)}
    if len(links) > MAX_LINKS:
        problems.append(f"{len(links)} distinct wikilinks in body (max {MAX_LINKS})")
    words = len(re.findall(r"[^\s>#*\-|]+", re.sub(r"\[!\w+\][-+]?", "", prose)))
    if a.words:
        print(f"WORDS {words}"); return 0
    if a.headline is not None:
        h = a.headline.strip()
        if not h:
            problems.append("headline is empty")
        elif "\n" in h:
            problems.append("headline must be one line")
        elif len(h) > MAX_HEADLINE:
            problems.append(f"headline is {len(h)} chars (max {MAX_HEADLINE})")
    lo, hi = int(a.min * 0.75), int(a.max * 1.35)
    if not lo <= words <= hi:
        problems.append(f"body is {words} words (allowed {lo}-{hi}, target {a.min}-{a.max})")
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
