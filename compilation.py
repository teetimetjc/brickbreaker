#!/usr/bin/env python3
"""
Weekly long-form YouTube episode (widescreen 1920x1080, just under 15 minutes): fresh rounds rendered from
scratch, a mix of normal clears/game overs, color battles and brick escapes, separated by "ROUND N" cards
that carry a running color leaderboard. The description gets YouTube chapters (one per round).

Why under 15:00: YouTube only allows longer uploads on phone-verified channels.

  python3 compilation.py                 # DRY RUN: render the episode into output/, upload nothing
  python3 compilation.py --live          # also upload to YouTube (needs the YT_* secrets)
  python3 compilation.py --minutes 3     # short test episode
"""
import argparse
import csv
import datetime as dt
import json
import math
import os
import random
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import battle  # noqa: E402
import brick_breaker_gen as gen  # noqa: E402
import escape  # noqa: E402
import pipeline  # noqa: E402
from publishers import youtube  # noqa: E402

W, H = 1920, 1080
FPS = gen.FPS
SR = 44100
CARD_S = 2.5
MAX_TOTAL_S = 14 * 60 + 40  # stay safely under YouTube's 15:00 limit for unverified channels
COLOR_RGB = {"RED": (255, 95, 95), "BLUE": (95, 175, 255), "GREEN": (80, 225, 150), "PURPLE": (195, 125, 255),
             "GOLD": (255, 210, 80), "YELLOW": (250, 210, 60)}
SHAPES = {"solid": "Wall", "checker": "Checkerboard", "stripes": "Stripes", "rings": "Rings", "heart": "Heart",
          "circle": "Circle", "diamond": "Diamond", "pyramid": "Pyramid"}


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd[:6])}...\n{r.stderr[-800:]}")


# --------------------------------------------------------------------------- cards
def chime_wav(path, secs, notes=(784, 1047)):
    n = int(secs * SR)
    mix = np.zeros(n, np.float32)
    for k, f in enumerate(notes):
        t = np.arange(int(0.6 * SR)) / SR
        w = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)) * np.exp(-t * 5) * 0.22
        i = int((0.15 + k * 0.12) * SR)
        mix[i:i + len(w)] += w[: max(0, n - i)]
    pcm = (np.tanh(mix) * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())


def leaderboard_line(d, wins, y, size):
    """Draw 'Red 3 · Blue 2 · ...' centered, each name in its color."""
    if not wins:
        return
    items = sorted(wins.items(), key=lambda kv: (-kv[1], kv[0]))
    f = gen.font(size)
    parts = [(f"{name.title()} {n}", COLOR_RGB.get(name, (230, 230, 240))) for name, n in items]
    sep = "   ·   "
    total = sum(d.textlength(p, font=f) for p, _ in parts) + d.textlength(sep, font=f) * (len(parts) - 1)
    x = W / 2 - total / 2
    for i, (txt, col) in enumerate(parts):
        d.text((x, y), txt, font=f, fill=col, anchor="lm")
        x += d.textlength(txt, font=f)
        if i < len(parts) - 1:
            d.text((x, y), sep, font=f, fill=(110, 110, 125), anchor="lm")
            x += d.textlength(sep, font=f)


def card_png(path, head, sub, wins=None, foot=None, head_color=(240, 240, 248), wins_title="WINS SO FAR"):
    img = Image.new("RGB", (W, H), (14, 14, 20))
    d = ImageDraw.Draw(img)
    # a strip of bricks along the top and bottom so cards feel like part of the show
    for row, y0 in ((0, 0), (1, H - 60)):
        for c in range(0, W, 120):
            col = gen.hsv((c / W + row * 0.5) % 1, 0.7, 0.85)
            d.rectangle((c + 4, y0 + 8, c + 116, y0 + 52), fill=col)
    d.text((W / 2, H * 0.36), head, font=gen.font(150), fill=head_color, anchor="mm")
    d.text((W / 2, H * 0.52), sub, font=gen.font(64), fill=(200, 200, 215), anchor="mm")
    if wins:
        d.text((W / 2, H * 0.66), wins_title, font=gen.font(34), fill=(130, 130, 145), anchor="mm")
        leaderboard_line(d, wins, H * 0.73, 52)
    if foot:
        d.text((W / 2, H * 0.86), foot, font=gen.font(40), fill=(150, 150, 165), anchor="mm")
    img.save(path)


def card_clip(path, png, secs=CARD_S):
    wav = path[:-4] + ".wav"
    chime_wav(wav, secs)
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-i", png, "-i", wav,
         "-t", f"{secs}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-ac", "2", "-shortest", path])
    os.remove(wav)


def normalize(src, dst):
    """Same audio format for every clip (stereo AAC 44.1 kHz) so they can be joined without re-encoding video."""
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
         "-ar", str(SR), "-ac", "2", dst])


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


# --------------------------------------------------------------------------- rounds
def render_round(kind, rng, path, target):
    """Render one widescreen round; re-roll designs that can't fit the target length. Returns metadata."""
    for attempt in range(8):
        seed = rng.randint(1, 10 ** 6)
        reject = None if attempt == 7 else target * 1.4
        try:
            if kind == "battle":
                cfg = dict(seed=seed, target=target, reject_over=reject, teams=pick_battle_teams(rng))
                return battle.make_battle(cfg, path)
            if kind == "escape":
                return escape.make_escape(dict(seed=seed, target=target, reject_over=reject), path)
            cfg = gen.random_cfg(rng, gen.default_cfg(size=gen.SIZES["landscape"], max_cell=30), target, target, 0.3)
            cfg["target"], cfg["reject_over"] = target, reject
            return gen.make_video(cfg, path)
        except gen.TooLong as e:
            print(f"  re-rolling ({e})")
    raise RuntimeError("could not render a round")


def pick_battle_teams(rng):
    return ("RED", "BLUE") if rng.random() < 0.6 else tuple(rng.sample(["RED", "BLUE", "GREEN", "PURPLE", "YELLOW"], 2))


def round_label(meta):
    if meta.get("mode") == "battle":
        a, b = meta["teams"]
        return f"{a.title()} vs {b.title()}"
    if meta.get("mode") == "escape":
        return "Brick Escape"
    shape = SHAPES.get(meta["pattern"], meta["pattern"].title())
    obst = {"none": "", "vault": " in a Vault", "pillars": " with Pillars", "shelves": " on Shelves",
            "funnel": " through a Funnel", "maze": " in a Maze"}.get(meta["obstacle"], "")
    return f"{shape}{obst}"


def round_sub_before(kind, rng):
    if kind == "battle":
        return rng.choice(["Pick a side!", "Who clears first?", "Same bricks. Same start."])
    if kind == "escape":
        return rng.choice(["4 balls. 1 exit.", "Pick your ball!", "Who escapes first?"])
    return rng.choice(["Will it clear?", "Can it make it?", "Wait for the last brick..."])


def plan(rng, n):
    kinds = []
    pool = ["battle", "escape", "normal"]
    while len(kinds) < n:
        rng.shuffle(pool)
        for k in pool:
            if not kinds or kinds[-1] != k:
                kinds.append(k)
    return kinds[:n]


def fmt_ts(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}" if sec < 3600 else f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def posted_within(days):
    path = os.path.join(HERE, "data", "posts.csv")
    if not os.path.exists(path):
        return False
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r.get("pattern") != "compilation":
                continue
            try:
                t = dt.datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc)
            except (KeyError, ValueError):
                continue
            if t >= cutoff:
                return True
    return False


def next_episode():
    path = os.path.join(HERE, "data", "posts.csv")
    if not os.path.exists(path):
        return 1
    with open(path, newline="") as f:
        return 1 + sum(1 for r in csv.DictReader(f) if r.get("pattern") == "compilation")


def make_episode(out_path, episode, seed, max_total=MAX_TOTAL_S):
    battle.configure(W, H)
    escape.configure(W, H)
    rng = random.Random(seed)
    work = out_path[:-4] + "_parts"
    os.makedirs(work, exist_ok=True)
    kinds = plan(rng, 40)
    clips, chapters, rounds, wins, t = [], [], [], {}, 0.0
    end_reserve = CARD_S + 1
    for i, kind in enumerate(kinds):
        target = rng.uniform(35, 62)
        if t + CARD_S + target + 3 + end_reserve > max_total:
            break
        k = i + 1
        print(f"[round {k}] {kind}, target {target:.0f}s")
        raw = os.path.join(work, f"r{k:02d}_raw.mp4")
        meta = render_round(kind, rng, raw, target)
        label = round_label(meta)
        if t + CARD_S + meta["duration"] + end_reserve > max_total:
            print("  too long for the remaining time; stopping here")
            break
        card = os.path.join(work, f"c{k:02d}.mp4")
        png = card[:-4] + ".png"
        card_png(png, f"ROUND {k}", label, wins if wins else None, foot=round_sub_before(kind, rng))
        card_clip(card, png)
        clip = os.path.join(work, f"r{k:02d}.mp4")
        normalize(raw, clip)
        chapters.append((t, f"Round {k} – {label}"))
        t += duration(card) + duration(clip)
        clips += [card, clip]
        if meta.get("winner"):
            wins[meta["winner"]] = wins.get(meta["winner"], 0) + 1
        rounds.append(dict(round=k, kind=kind, label=label, outcome=meta["outcome"], duration=meta["duration"],
                           winner=meta.get("winner"), margin_s=meta.get("margin_s")))
    # outro: final standings
    outro = os.path.join(work, "outro.mp4")
    top = max(wins.values()) if wins else 0
    leaders = [c for c, n in wins.items() if n == top]
    champ = leaders[0] if len(leaders) == 1 else None  # no champion on a tie
    card_png(outro[:-4] + ".png", "THAT'S A WRAP", f"Episode {episode} · {len(rounds)} rounds",
             wins or None, foot="New episode every week. Subscribe so you don't miss it!",
             head_color=COLOR_RGB.get(champ, (240, 240, 248)), wins_title="FINAL STANDINGS")
    card_clip(outro, outro[:-4] + ".png", 4)
    clips.append(outro)
    lst = os.path.join(work, "list.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.abspath(c)}'\n" for c in clips)
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
         "-movflags", "+faststart", out_path])
    total = duration(out_path)
    for f_ in os.listdir(work):
        os.remove(os.path.join(work, f_))
    os.rmdir(work)
    return dict(file=out_path, episode=episode, duration=round(total, 1), rounds=rounds, chapters=chapters,
                wins=wins, champion=champ)


def captions(ep, cfg):
    n = ep["episode"]
    title = f"Oddly Satisfying Brick Breaker | Color Battles & Brick Escapes | Episode {n}"
    lines = [f"Episode {n}: {len(ep['rounds'])} rounds of oddly satisfying brick breaker. Color battles, 4-ball "
             "brick escapes and satisfying clears, all simulated from scratch. Keep score and pick your color!",
             "", "Chapters:"]
    lines += [f"{fmt_ts(ts)} {name}" for ts, name in ep["chapters"]]
    if ep["wins"]:
        board = ", ".join(f"{c.title()} {w}" for c, w in sorted(ep["wins"].items(), key=lambda kv: -kv[1]))
        lines += ["", f"Final standings: {board}", "Which color are you rooting for next week? Comment below!"]
    lines += ["", "New episode every week. Daily Shorts on the channel too.", "",
              "#satisfying #oddlysatisfying #brickbreaker"]
    tags = cfg["youtube"]["tags"] + ["compilation", "color battle", "marble race", "relaxing", "asmr game"]
    comment = "Which color are you backing for next week's episode? 🔴🔵🟡🟢🟣"
    if ep["wins"]:
        comment = f"Final standings: {board}. Who takes it next week? Comment your color 👇"
    return {"title": title[:100], "description": "\n".join(lines), "tags": tags,
            "playlist": cfg["youtube"].get("playlists", {}).get("episode"),
            "comment": comment if cfg["youtube"].get("comments") else None}


def log_post(url, ep):
    path = os.path.join(HERE, "data", "posts.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=pipeline.LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"time_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), "x_url": "",
                    "youtube_url": url, "quote_of": "", "hook": f"Episode {ep['episode']}", "hashtags": "no",
                    "pattern": "compilation", "obstacle": f"{len(ep['rounds'])} rounds", "palette": "mixed",
                    "duration_s": round(ep["duration"]), "outcome": f"champion {ep['champion'] or '-'}",
                    "cleared_pct": "", "bricks": "", "start_balls": "", "bonus_every": "", "peak_balls": "",
                    "file": os.path.basename(ep["file"])})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--minutes", type=float, default=None, help="shorter episode for testing")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--outdir", default=os.path.join(HERE, "output"))
    ap.add_argument("--once-per-week", action="store_true",
                    help="timer runs: do nothing if an episode was already posted in the last 6 days")
    a = ap.parse_args()
    if a.once_per_week and posted_within(days=6):
        print("== an episode was already posted this week; nothing to do")
        return
    cfg = pipeline.load_config(os.path.join(HERE, "config.json"))
    live = a.live or os.environ.get("AUTOPOST_LIVE", "").lower() in ("1", "true", "yes")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = os.path.join(a.outdir, f"episode-{stamp}")
    os.makedirs(run_dir, exist_ok=True)
    n = next_episode()
    seed = a.seed if a.seed is not None else random.randint(1, 10 ** 9)
    print(f"== {'LIVE' if live else 'DRY RUN'} | episode {n} | seed {seed}")
    max_total = a.minutes * 60 if a.minutes else MAX_TOTAL_S
    ep = make_episode(os.path.join(run_dir, f"episode_{n:03d}.mp4"), n, seed, max_total)
    caps = captions(ep, cfg)
    with open(os.path.join(run_dir, "episode.json"), "w") as f:
        json.dump({"episode": ep, "captions": caps}, f, indent=2)
    with open(os.path.join(run_dir, "description.txt"), "w") as f:
        f.write(caps["title"] + "\n\n" + caps["description"] + "\n")
    print(f"== {fmt_ts(ep['duration'])} long, {len(ep['rounds'])} rounds, champion {ep['champion'] or 'tie'}")
    status = "dry-run"
    if live:
        if not youtube.configured():
            sys.exit("live upload needs YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN")
        url = youtube.post(ep["file"], caps, cfg.get("youtube", {}))
        status = f"[posted]({url})"
        print(f"  posted to youtube: {url}")
        log_post(url, ep)
    summary = (f"## Weekly episode {n} ({'LIVE' if live else 'DRY RUN'})\n\n"
               f"{fmt_ts(ep['duration'])} · {len(ep['rounds'])} rounds · champion {ep['champion']} · YouTube: {status}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary)


if __name__ == "__main__":
    main()
