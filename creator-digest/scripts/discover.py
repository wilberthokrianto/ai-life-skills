#!/usr/bin/env python3
"""creator-digest discovery: find new videos from a watchlist. Zero LLM tokens.

  discover.py find  --watchlist FILE --state FILE [--lookback N] [--max N]
  discover.py mark  --state FILE --status done|skipped ID [ID ...]
  discover.py finish --state FILE          # stamp last_run after a completed run

`find` prints JSON: {"process": [...], "backlog": [...], "stats": {...}}.
Candidates are only marked "seen" by `mark`, so a crashed run loses nothing.
Needs yt-dlp on PATH. Stdlib only otherwise.
"""
import argparse, json, re, subprocess, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULTS = {"lookback_days": 3, "max_videos": 6, "min_minutes": 8,
            "max_minutes": 240, "browser": "", "per_source": 10}
MAX_CATCHUP_DAYS = 14
BACKLOG_TTL_DAYS = 14
ATOM = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def parse_watchlist(path):
    """First ```watchlist fenced block. Lines: `kind: value | opt | opt=val`."""
    text = Path(path).read_text(encoding="utf-8")
    m = re.search(r"```watchlist\n(.*?)```", text, re.S)
    if not m:
        sys.exit(f"no ```watchlist block in {path}")
    settings, sources = dict(DEFAULTS), []
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = [s.strip() for s in line.split(":", 1)]
        key = key.lower()
        if key in ("channel", "person", "topic"):
            parts = [p.strip() for p in val.split("|")]
            opts = {}
            for p in parts[1:]:
                k, _, v = p.partition("=")
                opts[k.strip().lower()] = v.strip() or True
            sources.append({"kind": key, "value": parts[0], "opts": opts})
        elif key == "subscriptions":
            if val.lower() in ("true", "yes", "on", "1"):
                sources.append({"kind": "subscriptions", "value": "", "opts": {}})
        elif key in settings:
            settings[key] = type(settings[key])(val) if not isinstance(settings[key], str) else val
    return settings, sources


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 or r.stdout else ""


def ytdlp(args, browser):
    cmd = ["yt-dlp", "--no-warnings", "--ignore-errors"]
    if browser:
        cmd += ["--cookies-from-browser", browser]
    return run(cmd + args)


def channel_url(value):
    if value.startswith("http"):
        return value.rstrip("/")
    if value.startswith("@"):
        return f"https://www.youtube.com/{value}"
    if value.startswith("UC"):
        return f"https://www.youtube.com/channel/{value}"
    return f"https://www.youtube.com/@{value}"


def resolve_channel_id(value, state, browser):
    cache = state.setdefault("channel_ids", {})
    if value in cache:
        return cache[value]
    m = re.search(r"(UC[\w-]{22})", value)
    cid = m.group(1) if m else ytdlp(
        ["--flat-playlist", "-I", "1", "--print", "%(channel_id)s", channel_url(value) + "/videos"],
        browser).strip().splitlines()[:1]
    cid = cid if isinstance(cid, str) else (cid[0] if cid else "")
    if cid:
        cache[value] = cid
    return cid


def rss_ids(channel_id):
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            root = ET.fromstring(r.read())
    except Exception:
        return None
    return [e.findtext("yt:videoId", namespaces=ATOM) for e in root.findall("a:entry", ATOM)]


def flat_ids(args, browser):
    out = ytdlp(["--flat-playlist", "--print", "%(id)s\t%(title)s\t%(channel)s"] + args, browser)
    return [l.split("\t") for l in out.splitlines() if l.count("\t") >= 2]


def metadata(ids, browser):
    """One yt-dlp call for many ids. Returns {id: meta}."""
    if not ids:
        return {}
    fmt = "%(id)s\t%(title)s\t%(duration)s\t%(upload_date)s\t%(view_count)s\t%(channel)s\t%(live_status)s\t%(description).400s"
    out = ytdlp(["--skip-download", "--print", fmt] + [f"https://www.youtube.com/watch?v={i}" for i in ids], browser)
    res = {}
    for l in out.splitlines():
        p = l.split("\t")
        if len(p) < 8:
            continue
        vid, title, dur, up, views, chan, live, desc = p[0], p[1], p[2], p[3], p[4], p[5], p[6], "\t".join(p[7:])
        res[vid] = {"id": vid, "title": title, "channel": chan, "live_status": live,
                    "duration": int(dur) if dur.isdigit() else 0,
                    "views": int(views) if views.isdigit() else 0,
                    "uploaded": f"{up[:4]}-{up[4:6]}-{up[6:]}" if len(up) == 8 else "",
                    "url": f"https://www.youtube.com/watch?v={vid}", "desc": desc}
    return res


def load(path):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


def save(path, state):
    Path(path).write_text(json.dumps(state, indent=1, ensure_ascii=False))


def matches(src, meta):
    """Cheap relevance gate for person/topic searches (no tokens)."""
    hay = " ".join([meta["title"], meta["channel"], meta["desc"]]).casefold()
    q = src["value"].casefold()
    if src["kind"] == "person":
        return q in hay
    return all(t in hay for t in re.findall(r"\w+", q))


def cmd_find(a):
    settings, sources = parse_watchlist(a.watchlist)
    if a.lookback: settings["lookback_days"] = a.lookback
    if a.max: settings["max_videos"] = a.max
    state = load(a.state)
    seen = set(state.get("seen", {}))
    browser, per = settings["browser"], settings["per_source"]
    today = date.today()
    since = today - timedelta(days=settings["lookback_days"])
    if state.get("last_run"):
        since = min(since, date.fromisoformat(state["last_run"]) - timedelta(days=1))
    since = max(since, today - timedelta(days=MAX_CATCHUP_DAYS))

    cand = {}  # id -> {"srcs": [(src, rank)]}
    def add(vid, src):
        if vid and vid not in seen:
            cand.setdefault(vid, []).append(src)

    for src in sources:
        k = src["kind"]
        if k == "channel":
            cid = resolve_channel_id(src["value"], state, browser)
            ids = rss_ids(cid) if cid else None
            if ids is None:  # RSS failed: fall back to the channel's /videos tab
                ids = [r[0] for r in flat_ids(["-I", f"1:{per}", channel_url(src["value"]) + "/videos"], browser)]
            for vid in ids[:per]:
                add(vid, src)
        elif k in ("person", "topic"):
            for r in flat_ids([f"ytsearchdate{per}:{src['value']}"], browser):
                add(r[0], src)
        elif k == "subscriptions":
            for r in flat_ids(["-I", f"1:{per * 4}", ":ytsubs"], browser):
                add(r[0], src)

    backlog_prev = {b["id"]: b for b in state.get("backlog", [])
                    if date.fromisoformat(b["queued"]) >= today - timedelta(days=BACKLOG_TTL_DAYS)}
    meta = metadata([v for v in cand if v not in backlog_prev], browser)
    stats = {"scanned": len(cand), "seen_skipped": 0, "too_old": 0, "too_short": 0,
             "too_long": 0, "live": 0, "irrelevant": 0}
    pool = {}
    for vid, srcs in cand.items():
        m = meta.get(vid) or backlog_prev.get(vid)
        if not m:
            continue
        if m["live_status"] in ("is_live", "is_upcoming"): stats["live"] += 1; continue
        if m["uploaded"] and date.fromisoformat(m["uploaded"]) < since and vid not in backlog_prev:
            stats["too_old"] += 1; continue
        if m["duration"] < settings["min_minutes"] * 60: stats["too_short"] += 1; continue
        if m["duration"] > settings["max_minutes"] * 60 and not any(s["opts"].get("long") for s in srcs):
            stats["too_long"] += 1; continue
        gated = [s for s in srcs if s["kind"] in ("person", "topic")]
        if gated and not any(s["kind"] in ("channel", "subscriptions") for s in srcs):
            if not any(matches(s, m) and m["views"] >= int(s["opts"].get("min_views", 0) or 0) for s in gated):
                stats["irrelevant"] += 1; continue
        m = dict(m, deep=any(s["opts"].get("deep") for s in srcs),
                 sources=sorted({f"{s['kind']}:{s['value']}" for s in srcs} or []))
        m.pop("desc", None)
        pool[vid] = m
    for vid, b in backlog_prev.items():
        if vid not in pool and vid not in seen:
            pool[vid] = b
    # deep channels first, then explicit channels over searches, then newest
    def rank(m):
        explicit = any(s.startswith(("channel:", "subscriptions:")) for s in m.get("sources", []))
        return (not m.get("deep"), not explicit, m.get("uploaded", "") and -int(m["uploaded"].replace("-", "")))
    ordered = sorted(pool.values(), key=rank)
    process, backlog = ordered[:settings["max_videos"]], ordered[settings["max_videos"]:]
    state["backlog"] = [dict(b, queued=b.get("queued", today.isoformat())) for b in backlog]
    save(a.state, state)
    json.dump({"process": process, "backlog": backlog, "stats": stats,
               "since": since.isoformat(), "settings": settings}, sys.stdout, indent=1, ensure_ascii=False)


def cmd_mark(a):
    state = load(a.state)
    state.setdefault("seen", {}).update({i: {"status": a.status, "on": date.today().isoformat()} for i in a.ids})
    state["backlog"] = [b for b in state.get("backlog", []) if b["id"] not in a.ids]
    save(a.state, state)


def cmd_finish(a):
    state = load(a.state)
    state["last_run"] = date.today().isoformat()
    cutoff = (date.today() - timedelta(days=120)).isoformat()   # keep state small
    state["seen"] = {k: v for k, v in state.get("seen", {}).items() if v["on"] >= cutoff}
    save(a.state, state)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find"); f.add_argument("--watchlist", required=True); f.add_argument("--state", required=True)
    f.add_argument("--lookback", type=int); f.add_argument("--max", type=int); f.set_defaults(fn=cmd_find)
    m = sub.add_parser("mark"); m.add_argument("--state", required=True)
    m.add_argument("--status", choices=["done", "skipped"], required=True); m.add_argument("ids", nargs="+"); m.set_defaults(fn=cmd_mark)
    z = sub.add_parser("finish"); z.add_argument("--state", required=True); z.set_defaults(fn=cmd_finish)
    a = ap.parse_args(); a.fn(a)
