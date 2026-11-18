#!/usr/bin/env python3
"""
Autopost pipeline: render new brick-breaker videos and (optionally) post them.

  python3 pipeline.py              # DRY RUN: render videos + captions into output/, post nothing
  python3 pipeline.py --live       # also post to every platform whose keys are set
  python3 pipeline.py --count 3    # override videos_per_run from config.json

Quote-post mode (X only, one video): you pick a post, the pipeline renders a fresh video and quotes it.
  python3 pipeline.py --quote https://x.com/someone/status/123 --text "me trying to finish this week" --ending lose
  --ending win|lose|any   force how the video ends (default: random)
  --word MONDAY           spell a word in bricks instead of a random shape

Posting turns on per platform only when its secrets exist (see README.md):
  YouTube: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
  X:       X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
Setting AUTOPOST_LIVE=true has the same effect as --live (used by the scheduled workflow).
"""
import argparse
import datetime as dt
import json
import os
import random
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import brick_breaker_gen as gen  # noqa: E402
from publishers import youtube, x  # noqa: E402

PUBLISHERS = {"youtube": youtube, "x": x}


def load_config(path):
    with open(path) as f:
        return json.load(f)


def build_captions(meta, cfg, rng):
    """Captions tease the ending instead of spoiling it, so people watch to the end."""
    pool = cfg["captions"]["lose" if meta["outcome"] == "lose" else "win"]
    hook = rng.choice(pool)
    on_screen = meta["title"]
    yt_title = f"{on_screen} {' '.join(cfg['youtube']['hashtags'][:1])}".strip()[:100]
    yt_desc = "\n".join([
        hook,
        "",
        f"{meta['bricks']:,} bricks. {meta['start_balls']} starting ball(s)"
        + (f", +1 ball every {meta['bonus_every']} bricks." if meta["bonus_every"] else "."),
        "Missed balls are gone for good.",
        "",
        " ".join(cfg["youtube"]["hashtags"]),
    ])
    x_text = f"{hook}\n\n{' '.join(cfg['x']['hashtags'])}"
    return {"youtube": {"title": yt_title, "description": yt_desc, "tags": cfg["youtube"]["tags"]},
            "x": {"text": x_text}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--count", type=int, default=None)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--outdir", default=os.path.join(HERE, "output"))
    ap.add_argument("--seed", type=int, default=None, help="reproduce a run")
    ap.add_argument("--quote", default="", help="X post link (or id) to quote; posts to X only, 1 video")
    ap.add_argument("--text", default="", help="your own caption (default: a random hook)")
    ap.add_argument("--ending", default="any", choices=["any", "win", "lose"], help="force the ending")
    ap.add_argument("--word", default="", help="spell this word in bricks")
    a = ap.parse_args()
    a.quote, a.text, a.word = a.quote.strip(), a.text.strip(), a.word.strip().upper()
    if a.quote:
        x.tweet_id(a.quote)  # fail fast on a bad link, before spending time rendering

    cfg = load_config(a.config)
    live = a.live or os.environ.get("AUTOPOST_LIVE", "").lower() in ("1", "true", "yes")
    count = 1 if a.quote else (a.count or cfg["videos_per_run"])
    publishers = {"x": x} if a.quote else PUBLISHERS
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = os.path.join(a.outdir, stamp)
    os.makedirs(run_dir, exist_ok=True)
    master = random.Random(a.seed)

    ready = {name: p.configured() for name, p in publishers.items()}
    mode = "LIVE" if live else "DRY RUN"
    print(f"== {mode} | {count} video(s) | platforms with keys: "
          f"{', '.join(k for k, v in ready.items() if v) or 'none'}")
    if a.quote:
        print(f"== quote mode: will quote {a.quote}")
        if live and not ready["x"]:
            sys.exit("quote mode needs the X keys (X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET)")

    results = []
    for i in range(count):
        # The length tuner occasionally can't hit the target for a design (e.g. huge bricks + 1 ball) and
        # overshoots; re-roll a fresh design rather than post a 2-minute video.
        too_long = cfg["max_len_sec"] * 1.3
        for attempt in range(3):
            vcfg = gen.random_cfg(master, gen.default_cfg(), cfg["min_len_sec"], cfg["max_len_sec"],
                                  cfg["game_over_share"])
            if a.ending != "any":
                vcfg["lose"], vcfg["outcome"] = True, a.ending
            if a.word:
                # no walls (they cut letters) and the smallest bricks (bigger ones make letters unreadable)
                vcfg.update(pattern="text", text=a.word, obstacle="none", cell=20, balls=None, split_every=0)
            name = f"{i + 1:02d}_{vcfg['pattern']}_{vcfg['obstacle']}_{vcfg['seed']}.mp4"
            path = os.path.join(run_dir, name)
            print(f"[{i + 1}/{count}] rendering {name}")
            meta = gen.make_video(vcfg, path)
            if meta["duration"] <= too_long or attempt == 2:
                break
            print(f"  {meta['duration']:.0f}s is too long (> {too_long:.0f}s); re-rolling")
            os.remove(path)
        caps = build_captions(meta, cfg, master)
        if a.text:
            caps["x"]["text"] = a.text  # your words only; no hashtags (they look spammy on a reply-style quote)
        if a.quote:
            caps["x"]["quote"] = a.quote
            if not a.text:
                caps["x"]["text"] = caps["x"]["text"].split("\n")[0]
        entry = {"video": meta, "captions": caps, "posts": {}}

        for pname, pub in publishers.items():
            if not ready[pname]:
                entry["posts"][pname] = {"status": "skipped", "reason": "no keys yet"}
            elif not live:
                entry["posts"][pname] = {"status": "dry-run"}
            else:
                try:
                    url = pub.post(path, caps[pname], cfg.get(pname, {}))
                    entry["posts"][pname] = {"status": "posted", "url": url}
                    print(f"  posted to {pname}: {url}")
                except Exception as e:  # keep going so one platform can't block the other
                    traceback.print_exc()
                    entry["posts"][pname] = {"status": "error", "error": str(e)}
        with open(path[:-4] + ".json", "w") as f:
            json.dump(entry, f, indent=2)
        results.append(entry)

    write_captions(run_dir, results)
    with open(os.path.join(run_dir, "run_log.json"), "w") as f:
        json.dump({"mode": mode, "time_utc": stamp, "results": results}, f, indent=2)
    write_summary(mode, results)
    if any(p.get("status") == "error" for r in results for p in r["posts"].values()):
        sys.exit(1)


def write_captions(run_dir, results):
    """One file with every video's captions, for copy-pasting when posting by hand."""
    out = []
    for r in results:
        v, c = r["video"], r["captions"]
        ending = "CLEARED" if v["outcome"] == "win" else f"GAME OVER at {v['cleared_pct']}%"
        out += [f"=== {os.path.basename(v['file'])}  ({v['duration']:.0f}s, {ending})",
                "X caption:", c["x"]["text"], "",
                "YouTube title:", c["youtube"]["title"], "", ""]
    with open(os.path.join(run_dir, "captions.txt"), "w") as f:
        f.write("\n".join(out))


def write_summary(mode, results):
    lines = [f"## Brick breaker autopost ({mode})", "",
             "| Video | Length | Ending | YouTube | X |", "|---|---|---|---|---|"]
    for r in results:
        v, p = r["video"], r["posts"]

        def cell(k):
            s = p.get(k, {"status": "n/a"})
            return f"[posted]({s['url']})" if s["status"] == "posted" else s["status"]

        ending = "cleared" if v["outcome"] == "win" else f"game over at {v['cleared_pct']}%"
        lines.append(f"| {os.path.basename(v['file'])} | {v['duration']:.0f}s | {ending} | {cell('youtube')} | {cell('x')} |")
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
