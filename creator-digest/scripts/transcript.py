#!/usr/bin/env python3
"""Fetch a YouTube transcript as compact text. Zero LLM tokens.

  transcript.py VIDEO_ID --out DIR [--lang en,id] [--browser chrome]

Prefers uploaded captions over auto-captions, in --lang order. Writes DIR/<id>.txt with a
`[M:SS]` marker roughly every 60s (not per caption line, to keep it small).
Prints one JSON line: {"id","path","words","seconds","lang","track","source"} or {"id","error"}.
No captions => error "no_captions" (scheduled runs skip rather than pay for audio transcription).
"""
import argparse, glob, json, subprocess, sys, tempfile
from pathlib import Path

STEP = 60


def stamp(s):
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def parse_json3(path):
    ev = json.loads(Path(path).read_text(encoding="utf-8")).get("events", [])
    lines, last, nxt, buf = [], "", 0, []
    for e in ev:
        segs = e.get("segs")
        if not segs:
            continue
        t = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        if not t or t == last:
            continue
        last = t
        start = e.get("tStartMs", 0) / 1000
        if start >= nxt:
            if buf:
                lines.append(" ".join(buf)); buf = []
            lines.append(f"[{stamp(start)}]")
            nxt = (int(start) // STEP + 1) * STEP
        buf.append(t)
    if buf:
        lines.append(" ".join(buf))
    dur = (ev[-1].get("tStartMs", 0) + ev[-1].get("dDurationMs", 0)) / 1000 if ev else 0
    return "\n".join(lines), dur


def pick_track(info, langs):
    """(code, is_auto) for the best caption track, or None.
    Order: uploaded captions in `langs` order, then each language's original auto
    captions (`<lang>-orig`), then any auto track in `langs` (may be machine-translated)."""
    subs, auto = info.get("subtitles") or {}, info.get("automatic_captions") or {}
    for lang in langs:
        for code in sorted(subs, key=len):
            if code == lang or code.startswith(lang + "-"):
                return code, False
    for lang in langs:
        if f"{lang}-orig" in auto:
            return f"{lang}-orig", True
    for lang in langs:
        if lang in auto:
            return lang, True
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id"); ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="en,id", help="comma-separated preference order")
    ap.add_argument("--browser", default="")
    a = ap.parse_args()
    langs = [l.strip() for l in a.lang.split(",") if l.strip()]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={a.id}"
    cookies = ["--cookies-from-browser", a.browser] if a.browser else []
    r = subprocess.run(["yt-dlp", "--no-warnings", "-J", "--skip-download"] + cookies + [url],
                       capture_output=True, text=True)
    try:
        track = pick_track(json.loads(r.stdout), langs)
    except ValueError:
        track = None
    if not track:
        print(json.dumps({"id": a.id, "error": "no_captions"})); return 1
    code, is_auto = track
    with tempfile.TemporaryDirectory() as tmp:
        cmd = ["yt-dlp", "--no-warnings", "--skip-download",
               "--write-auto-subs" if is_auto else "--write-subs",
               "--sub-langs", code, "--sub-format", "json3", "-o", f"{tmp}/%(id)s"] + cookies + [url]
        subprocess.run(cmd, capture_output=True, text=True)
        files = glob.glob(f"{tmp}/{a.id}.*.json3")
        if not files:
            print(json.dumps({"id": a.id, "error": "no_captions"})); return 1
        text, dur = parse_json3(files[0])
    path = out / f"{a.id}.txt"
    path.write_text(text, encoding="utf-8")
    print(json.dumps({"id": a.id, "path": str(path), "words": len(text.split()), "seconds": int(dur),
                      "lang": code.split("-")[0], "track": code, "source": "auto" if is_auto else "manual"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
