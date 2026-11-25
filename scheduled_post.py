#!/usr/bin/env python3
"""
Posts pre-made, approved Brick Picks videos at set times (data/scheduled/queue.json). Every run posts each entry whose
time has come and that isn't in data/scheduled/done.csv yet, so a late or duplicate trigger can never post twice.
Entries more than 3 hours past their time are skipped (a pregame pick after kickoff is pointless) and reported.

  python3 scheduled_post.py            # dry run: say what is due
  python3 scheduled_post.py --live     # post what is due
"""
import argparse
import csv
import datetime as dt
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sports  # noqa: E402

QUEUE = os.path.join(HERE, "data", "scheduled", "queue.json")
DONE = os.path.join(HERE, "data", "scheduled", "done.csv")


def done_ids():
    if not os.path.exists(DONE):
        return set()
    with open(DONE, newline="") as f:
        return {r["id"] for r in csv.DictReader(f)}


def mark(entry, status, urls):
    new = not os.path.exists(DONE)
    with open(DONE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "time_utc", "status", "urls"])
        if new:
            w.writeheader()
        w.writerow(dict(id=entry["id"], time_utc=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                        status=status, urls=" ".join(urls.values())))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    live = a.live or os.environ.get("AUTOPOST_LIVE", "").lower() in ("1", "true", "yes")
    cfg = json.load(open(os.path.join(HERE, "config.json")))
    now = dt.datetime.now(dt.timezone.utc)
    done = done_ids()
    lines = [f"## Scheduled posts ({'LIVE' if live else 'DRY RUN'}) at {now:%Y-%m-%d %H:%M} UTC"]
    for e in json.load(open(QUEUE)):
        at = dt.datetime.strptime(e["at_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc)
        if e["id"] in done:
            lines.append(f"- {e['id']}: already done")
            continue
        if now < at:
            lines.append(f"- {e['id']}: waiting until {e['at_utc']} UTC")
            continue
        if now > at + dt.timedelta(hours=3):
            lines.append(f"- {e['id']}: MISSED (more than 3 h late), not posted")
            if live:
                mark(e, "missed", {})
            continue
        random.seed(e["id"])
        caps = sports.captions("pick", e["away"], e["home"], e["pick"], "", "", (0, 0), cfg, "NFL")
        lines.append(f"- {e['id']}: DUE -> {caps['youtube']['title']}")
        if not live:
            continue
        from publishers import tiktok, x, youtube
        pubs, urls = {"youtube": youtube, "x": x, "tiktok": tiktok}, {}
        path = os.path.join(HERE, e["file"])
        for name in [p.strip() for p in e.get("platforms", "youtube,x").split(",") if p.strip() in pubs]:
            if not pubs[name].configured():
                lines.append(f"  - {name}: skipped (no keys)")
                continue
            try:
                urls[name] = pubs[name].post(path, caps[name], cfg.get(name, {}))
                lines.append(f"  - {name}: {urls[name]}")
            except Exception as ex:  # keep going with the other platforms
                lines.append(f"  - {name}: ERROR {ex}")
        mark(e, "posted" if urls else "failed", urls)
        new = not os.path.exists(sports.RECORD)
        with open(sports.RECORD, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=sports.FIELDS)
            if new:
                w.writeheader()
            w.writerow(dict(time_utc=now.strftime("%Y-%m-%d %H:%M"), mode="pick", league="NFL", away=e["away"],
                            home=e["home"], pick=e["pick"], winner="", score="", correct="",
                            url=urls.get("youtube") or urls.get("x") or ""))
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
