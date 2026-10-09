#!/usr/bin/env python3
"""Fetch a YouTube transcript as compact text. Zero LLM tokens.

  transcript.py VIDEO_ID --out DIR [--lang en] [--browser chrome]

Prefers uploaded captions over auto-captions. Writes DIR/<id>.txt with a
`[M:SS]` marker roughly every 60s (not per caption line, to keep it small).
Prints one JSON line: {"id","path","words","seconds","source"} or {"id","error"}.
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id"); ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="en"); ap.add_argument("--browser", default="")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cmd = ["yt-dlp", "--no-warnings", "--skip-download", "--write-subs", "--write-auto-subs",
               "--sub-langs", f"{a.lang}.*,{a.lang}", "--sub-format", "json3",
               "-o", f"{tmp}/%(id)s", f"https://www.youtube.com/watch?v={a.id}"]
        if a.browser:
            cmd[1:1] = ["--cookies-from-browser", a.browser]
        subprocess.run(cmd, capture_output=True, text=True)
        files = sorted(glob.glob(f"{tmp}/{a.id}.*.json3"))
        if not files:
            print(json.dumps({"id": a.id, "error": "no_captions"})); return 1
        # an uploaded track has the bare language code; auto tracks are e.g. en-orig / en.*
        manual = [f for f in files if Path(f).name.split(".")[-2] == a.lang]
        pick = (manual or files)[0]
        text, dur = parse_json3(pick)
    path = out / f"{a.id}.txt"
    path.write_text(text, encoding="utf-8")
    print(json.dumps({"id": a.id, "path": str(path), "words": len(text.split()),
                      "seconds": int(dur), "source": "manual" if manual else "auto"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
