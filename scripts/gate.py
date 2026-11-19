#!/usr/bin/env python3
"""
Random posting time inside a window, with exactly one post per window.

An outside timer (cron-job.org) starts the workflow every `slot_minutes` during each window in
config.json `post_windows` (local time `post_timezone`). Each start ("knock") runs this gate first:

  * outside every window             -> skip
  * this window already has a post   -> skip   (data/posts.csv, freshly pulled)
  * otherwise post with probability 1 / (knocks left in the window, this one included)

That makes the posting knock uniformly random across the window and guarantees one post even if some
knocks fail (the last knock always posts). A small random wait is added so posts don't land on :00/:30.

Writes `post=true|false` and `sleep=<seconds>` to $GITHUB_OUTPUT (or prints them).
  python3 scripts/gate.py [--now 2026-11-19T08:30] [--seed 1]
"""
import argparse
import csv
import datetime as dt
import json
import math
import os
import random
import sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def windows_today(cfg, now_local):
    out = []
    for w in cfg.get("post_windows", []):
        sh, sm = map(int, w["start"].split(":"))
        eh, em = map(int, w["end"].split(":"))
        start = now_local.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = now_local.replace(hour=eh, minute=em, second=0, microsecond=0)
        out.append((w["name"], start, end))
    return out


def posted_since(start_utc):
    path = os.path.join(HERE, "data", "posts.csv")
    if not os.path.exists(path):
        return False
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r.get("pattern") == "compilation" or not (r.get("x_url") or r.get("youtube_url")):
                continue
            try:
                t = dt.datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc)
            except (KeyError, ValueError):
                continue
            if t >= start_utc:
                return True
    return False


def decide(cfg, now_utc, rng):
    tz = ZoneInfo(cfg.get("post_timezone", "America/Chicago"))
    now = now_utc.astimezone(tz)
    slot = cfg.get("slot_minutes", 30)
    for name, start, end in windows_today(cfg, now):
        if start <= now < end:
            if posted_since(start.astimezone(dt.timezone.utc)):
                return False, 0, f"{name} window already has a post"
            left = max(1, math.ceil((end - now).total_seconds() / 60 / slot))
            post = rng.random() < 1 / left
            wait = rng.randint(0, cfg.get("max_random_wait_minutes", 10) * 60) if post else 0
            return post, wait, f"{name} window, {left} knock(s) left incl. this one -> {'POST' if post else 'wait'}"
    return False, 0, f"outside all posting windows ({now:%H:%M} {tz.key})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", default=None, help="pretend time (UTC, ISO) for testing")
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()
    with open(os.path.join(HERE, "config.json")) as f:
        cfg = json.load(f)
    now = (dt.datetime.fromisoformat(a.now).replace(tzinfo=dt.timezone.utc) if a.now
           else dt.datetime.now(dt.timezone.utc))
    post, wait, why = decide(cfg, now, random.Random(a.seed))
    print(f"gate: {why}" + (f"; random wait {wait // 60} min" if post else ""))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"post={'true' if post else 'false'}\nsleep={wait}\n")
    else:
        print(f"post={'true' if post else 'false'} sleep={wait}")


if __name__ == "__main__":
    sys.exit(main())
