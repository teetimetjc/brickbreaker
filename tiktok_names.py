#!/usr/bin/env python3
"""
TIKTOK MIDDAY DRAFT: "random names" - 2 popular first names (data/popular_names.txt) spelled in bricks and broken,
sent to the TikTok inbox as a DRAFT (TikTok only; never YouTube/X). Viewers whose name shows up comment, and everyone
else comments theirs (-> real name requests Trevor can answer with --names / "Reply with video").

Names used in the last 60 days are skipped (data/tiktok_names_used.csv). The caption is written to
output/tiktok_names/captions.txt and the run summary (inbox drafts can't carry one).

  python3 tiktok_names.py            # render only
  python3 tiktok_names.py --live     # render + send to TikTok drafts
"""
import argparse
import csv
import datetime as dt
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import namereq  # noqa: E402

NAMES = os.path.join(HERE, "data", "popular_names.txt")
USED = os.path.join(HERE, "data", "tiktok_names_used.csv")
CAPTIONS = ["Is your name here? 👀 Comment yours and it might be next 🧱",
            "{a} and {b}, this one's for you 🧱 Who's next? Comment your name 👇",
            "Breaking random names brick by brick 🧱 Is yours next? 👇",
            "Know a {a} or {b}? Tag them 👀 Comment your name for the next one 🧱",
            "POV: your name gets broken brick by brick 🧱 Comment it 👇"]
TAGS = "#satisfying #brickbreaker #yourname #oddlysatisfying"


def recent_used(days=60):
    if not os.path.exists(USED):
        return set()
    cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    with open(USED, newline="") as f:
        return {r["name"].lower() for r in csv.DictReader(f) if r["date"] >= cut}


def pick(n, rng):
    with open(NAMES) as f:
        pool = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    used = recent_used()
    fresh = [p for p in pool if p.lower() not in used] or pool
    return rng.sample(fresh, n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--count", type=int, default=2)
    a = ap.parse_args()
    live = a.live or os.environ.get("AUTOPOST_LIVE", "").lower() in ("1", "true", "yes")
    import json
    from zoneinfo import ZoneInfo
    cfg = json.load(open(os.path.join(HERE, "config.json")))
    today = dt.datetime.now(ZoneInfo(cfg.get("post_timezone", "America/Chicago"))).strftime("%Y-%m-%d")
    if live and os.environ.get("GITHUB_EVENT_NAME") == "schedule" and today in cfg.get("quiet_dates", []):
        print(f"quiet day {today}: no midday draft")
        return
    rng = random.Random()
    names = pick(a.count, rng)
    outdir = os.path.join(HERE, "output", "tiktok_names")
    os.makedirs(outdir, exist_ok=True)
    path, _ = namereq.render([{"name": n} for n in names], outdir, rng.randint(1, 10 ** 6),
                             card_text="COMMENT YOUR NAME")
    cap = rng.choice(CAPTIONS).format(a=names[0], b=names[-1]) + " " + TAGS
    with open(os.path.join(outdir, "captions.txt"), "w") as f:
        f.write(f"Names: {', '.join(names)}\nTikTok caption (paste when you post the draft):\n{cap}\n")
    print(f"names: {', '.join(names)}\ncaption: {cap}")
    lines = [f"## TikTok midday draft ({'LIVE' if live else 'DRY RUN'})", f"Names: {', '.join(names)}",
             f"Caption to paste: {cap}"]
    if live:
        from publishers import tiktok
        if not tiktok.configured():
            sys.exit("TikTok keys/token missing")
        res = tiktok.post(path, {"text": cap}, {})
        print(f"sent: {res}")
        lines.append(f"Sent to TikTok drafts: {res}")
        new = not os.path.exists(USED)
        with open(USED, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["date", "name"])
            today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
            for n in names:
                w.writerow([today, n])
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a") as f:
            f.write("\n\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
