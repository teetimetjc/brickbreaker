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

import battle  # noqa: E402
import brick_breaker_gen as gen  # noqa: E402
from publishers import youtube, x  # noqa: E402

PUBLISHERS = {"youtube": youtube, "x": x}


def load_config(path):
    with open(path) as f:
        return json.load(f)


SHAPE_NAMES = {"solid": "wall", "checker": "checkerboard", "stripes": "stripes", "rings": "rings",
               "heart": "heart", "circle": "circle", "diamond": "diamond", "pyramid": "pyramid"}

# Hooks tease the ending, never spoil it. "win"/"lose" hooks only go on videos that really end that way.
HOOKS = {
    "any": ["Will it clear? Watch to the end", "{count} bricks vs {balls}", "Don't look away", "This one gets intense", "Turn the sound on for this one",
            "{count} bricks. Place your bets."],
    "win": ["Guess how long this takes", "Wait for the last brick", "Don't look away before 100%",
            "How fast can it clear {count} bricks?", "Satisfying all the way to the last brick",
            "Watch the {shape} disappear"],
    "lose": ["Will it make it?", "Every miss costs a ball", "Guess the final %", "Don't drop the last ball...",
             "How close can it get?", "Does it clear or run out of balls?"],
    "single": ["Can 1 ball clear the {shape}?", "1 ball vs {count} bricks"],
    "bonus": ["Every {k} bricks = 1 more ball", "It multiplies every {k} bricks...", "Watch it multiply",
              "How many balls does it take?"],
    "vault": ["Can {balls} break into the vault?", "Only one way in...", "One tiny gap. Can it get in?"],
    "maze": ["Can it find a way through the maze?", "{count} bricks hidden in a maze"],
    "funnel": ["Everything has to go through the funnel", "The funnel decides everything"],
    "pillars": ["{count} bricks behind the pillars", "Can it get around the pillars?"],
    "shelves": ["Can it reach the top shelf?", "{count} bricks stacked on shelves"],
    # color battles: invite people to pick a side (comments are what the algorithms reward)
    "battle": ["{a} or {b}? Pick before it starts", "{a} vs {b}. Comment your pick", "Which color clears first?",
               "{a} vs {b}. No switching sides", "Same bricks, same start. Who wins?", "Pick a side: {a} or {b}",
               "{a} vs {b}. This one goes down to the wire"],
}


def recent_hooks(n):
    """Hooks of the last n live posts (data/posts.csv), so titles don't repeat back to back."""
    import csv
    path = os.path.join(HERE, "data", "posts.csv")
    if n <= 0 or not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return [r.get("hook", "") for r in csv.DictReader(f)][-n:]


def pick_hook(meta, vcfg, cfg, rng, avoid):
    if meta.get("mode") == "battle":
        a, b = (t.title() for t in meta["teams"])
        options = sorted({h.format(a=a, b=b) for h in HOOKS["battle"]})
        fresh = [h for h in options if h not in avoid] or options
        return rng.choice(fresh)
    outcome = "lose" if meta["outcome"] == "lose" else "win"
    pool = HOOKS["any"] + HOOKS[outcome] * 2
    if meta["start_balls"] == 1:
        pool += HOOKS["single"] * 2
    if meta["bonus_every"]:
        pool += HOOKS["bonus"]
    pool += HOOKS.get(vcfg.get("obstacle"), []) * 2
    shape = vcfg.get("text") if vcfg.get("pattern") == "text" else SHAPE_NAMES.get(vcfg.get("pattern"), "wall")
    b = meta["start_balls"]
    fill = dict(count=f"{meta['bricks']:,}", shape=shape, k=meta["bonus_every"], balls=f"{b} ball{'s' if b != 1 else ''}")
    options = sorted({h.format(**fill) for h in pool})
    fresh = [h for h in options if h not in avoid] or options
    return rng.choice(fresh)


def build_captions(meta, vcfg, cfg, rng, avoid=()):
    """One hook per video, chosen to fit how it really ends, used for both the YouTube title and the X post."""
    hook = pick_hook(meta, vcfg, cfg, rng, set(avoid))
    yt_title = f"{hook} {' '.join(cfg['youtube']['hashtags'][:1])}".strip()[:100]
    b = meta["start_balls"]
    setup = f"{meta['bricks']:,} bricks. {b} starting ball{'s' if b != 1 else ''}"
    setup += f", plus 1 more every {meta['bonus_every']} bricks." if meta["bonus_every"] else "."
    if meta.get("mode") == "battle":
        a, b = (t.title() for t in meta["teams"])
        setup = (f"{a} vs {b}: same {meta['bricks']:,} bricks, same start, same speed. Only the bounces differ. "
                 f"First side to clear wins.")
        yt_desc = "\n".join([hook, "", setup, "Comment your pick before the end!", "",
                              " ".join(cfg["youtube"]["hashtags"])])
    else:
        yt_desc = "\n".join([hook, "", setup, "Missed balls are gone for good.", "",
                              " ".join(cfg["youtube"]["hashtags"])])
    # A/B test: only some X posts get hashtags (config x.hashtag_share); logged so views can be compared later.
    use_tags = rng.random() < cfg["x"].get("hashtag_share", 1.0)
    x_text = f"{hook}\n\n{' '.join(cfg['x']['hashtags'])}" if use_tags else hook
    return {"youtube": {"title": yt_title, "description": yt_desc, "tags": cfg["youtube"]["tags"]},
            "x": {"text": x_text, "hook": hook, "hashtags": use_tags}}


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
    ap.add_argument("--style", default="auto", choices=["auto", "normal", "battle"],
                    help="battle = split-screen color race; auto = battle with probability config battle_share")
    ap.add_argument("--platforms", default="all", help="comma list to post to, e.g. youtube or x,youtube (default all)")
    a = ap.parse_args()
    a.quote, a.text, a.word = a.quote.strip(), a.text.strip(), a.word.strip().upper()
    if a.quote:
        x.tweet_id(a.quote)  # fail fast on a bad link, before spending time rendering

    cfg = load_config(a.config)
    live = a.live or os.environ.get("AUTOPOST_LIVE", "").lower() in ("1", "true", "yes")
    count = 1 if a.quote else (a.count or cfg["videos_per_run"])
    publishers = {"x": x} if a.quote else dict(PUBLISHERS)
    if a.platforms.strip() not in ("", "all"):
        want = {p.strip().lower() for p in a.platforms.split(",")}
        publishers = {k: v for k, v in publishers.items() if k in want}
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
    avoid = recent_hooks(cfg.get("recent_hooks_to_avoid", 10))
    for i in range(count):
        # The length tuner occasionally can't hit the target for a design (e.g. huge bricks + 1 ball) and
        # overshoots; re-roll a fresh design rather than post a 2-minute video.
        too_long = cfg["max_len_sec"] * 1.3
        for attempt in range(8):
            vcfg = gen.random_cfg(master, gen.default_cfg(max_cell=cfg.get("max_brick_px")), cfg["min_len_sec"],
                                  cfg["max_len_sec"], cfg["game_over_share"])
            if a.ending != "any":
                vcfg["lose"], vcfg["outcome"] = True, a.ending
            if a.word:
                # no walls (they cut letters) and the smallest bricks (bigger ones make letters unreadable)
                vcfg.update(pattern="text", text=a.word, obstacle="none", cell=20, balls=None, split_every=0)
            last = attempt == 7
            vcfg["reject_over"] = None if last else too_long  # checked before rendering; last try renders anyway
            if attempt == 0:
                is_battle = a.style == "battle" or (a.style == "auto" and not a.word
                                                    and master.random() < cfg.get("battle_share", 0))
            if is_battle:
                vcfg = dict(seed=vcfg["seed"], target=vcfg["target"], reject_over=vcfg["reject_over"])
            name = (f"{i + 1:02d}_battle_{vcfg['seed']}.mp4" if is_battle
                    else f"{i + 1:02d}_{vcfg['pattern']}_{vcfg['obstacle']}_{vcfg['seed']}.mp4")
            path = os.path.join(run_dir, name)
            print(f"[{i + 1}/{count}] rendering {name}")
            try:
                meta = battle.make_battle(vcfg, path) if is_battle else gen.make_video(vcfg, path)
            except gen.TooLong as e:
                print(f"  skipped before rendering: {e}; re-rolling")
                continue
            if meta["duration"] <= too_long or last:
                break
            print(f"  {meta['duration']:.0f}s is too long (> {too_long:.0f}s); re-rolling")
            os.remove(path)
        caps = build_captions(meta, vcfg, cfg, master, avoid)
        avoid.append(caps["x"]["hook"])
        if a.text:
            caps["x"]["hook"], caps["x"]["hashtags"] = a.text, False
            caps["x"]["text"] = a.text  # your words only; no hashtags (they look spammy on a reply-style quote)
        if a.quote:
            caps["x"]["quote"] = a.quote
            if not a.text:
                caps["x"]["text"], caps["x"]["hashtags"] = caps["x"]["hook"], False
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
    if live:
        append_post_log(results, a.quote)
    with open(os.path.join(run_dir, "run_log.json"), "w") as f:
        json.dump({"mode": mode, "time_utc": stamp, "results": results}, f, indent=2)
    write_summary(mode, results)
    if any(p.get("status") == "error" for r in results for p in r["posts"].values()):
        sys.exit(1)


LOG_FIELDS = ["time_utc", "x_url", "youtube_url", "quote_of", "hook", "hashtags", "pattern", "obstacle", "palette",
              "duration_s", "outcome", "cleared_pct", "bricks", "start_balls", "bonus_every", "peak_balls", "file"]


def append_post_log(results, quote):
    """Permanent record of every live post (data/posts.csv, committed by the workflow) for the view-count review."""
    import csv
    path = os.path.join(HERE, "data", "posts.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        for r in results:
            v, c, p = r["video"], r["captions"]["x"], r["posts"]
            urls = {k: p.get(k, {}).get("url", "") for k in ("x", "youtube")}
            if not any(urls.values()):
                continue
            w.writerow({"time_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                        "x_url": urls["x"], "youtube_url": urls["youtube"], "quote_of": quote or "",
                        "hook": c.get("hook", ""), "hashtags": "yes" if c.get("hashtags") else "no",
                        "pattern": v["pattern"], "obstacle": v["obstacle"], "palette": v["palette"],
                        "duration_s": round(v["duration"]), "outcome": v["outcome"], "cleared_pct": v["cleared_pct"],
                        "bricks": v["bricks"], "start_balls": v["start_balls"], "bonus_every": v["bonus_every"],
                        "peak_balls": v["peak_balls"], "file": os.path.basename(v["file"])})


def ending_text(v):
    if v.get("mode") == "battle":
        return f"{v['outcome']} by {v['margin_s']}s"
    return "cleared" if v["outcome"] == "win" else f"game over at {v['cleared_pct']}%"


def write_captions(run_dir, results):
    """One file with every video's captions, for copy-pasting when posting by hand."""
    out = []
    for r in results:
        v, c = r["video"], r["captions"]
        ending = ending_text(v).upper()
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

        ending = ending_text(v)
        lines.append(f"| {os.path.basename(v['file'])} | {v['duration']:.0f}s | {ending} | {cell('youtube')} | {cell('x')} |")
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
