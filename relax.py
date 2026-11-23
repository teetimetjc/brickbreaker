#!/usr/bin/env python3
"""
RELAX VIDEOS: long-form widescreen (1920x1080) "1 hour of oddly satisfying brick breaking" for background watching
(study / sleep / relax). Long videos are the only thing that counts toward YouTube's 4,000 watch hours, and people
leave these playing, so one view can be worth 20-60 minutes.

A video is a chain of calm SCENES (3-5 min each): closed floor (never GAME OVER), a few slow balls, fine bricks,
calm shapes/walls, soft rounded notes over a quiet ambient pad, no end cards or text on screen. Scenes fade into each
other. Every video gets a different set of shapes, palettes and scene lengths (no two alike).

  python3 relax.py --minutes 3 --out sample.mp4          # quick sample for review
  python3 relax.py --minutes 60 --out relax.mp4 --live   # full video, uploaded to YouTube + thumbnail
"""
import argparse
import csv
import datetime as dt
import os
import random
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import brick_breaker_gen as gen  # noqa: E402

CALM_PATTERNS = ["solid", "heart", "circle", "diamond", "pyramid", "rings", "checker", "stripes"]
CALM_OBSTACLES = ["none", "none", "none", "pillars", "shelves"]
FADE = 1.5  # seconds of fade at each scene boundary


def scene_cfg(rng, seconds, used):
    pats = [p for p in CALM_PATTERNS if p not in used[-3:]] or CALM_PATTERNS
    cfg = gen.default_cfg(size=gen.SIZES["landscape"])
    cfg.update(seed=rng.randint(1, 10 ** 6), pattern=rng.choice(pats), obstacle=rng.choice(CALM_OBSTACLES),
               palette=rng.choice(list(gen.PALETTES)), lose=False, outcome="win", hp=1, balls=None, split_every=0,
               target=seconds, max_len=seconds * 1.35, end_card=False, soft_audio=True, cold_open=False,
               max_px_per_sec=rng.uniform(520, 680), max_cell=36)  # unhurried balls; tuner adds balls instead
    return cfg


def fade(src, dst, dur):
    out = max(0.0, dur - FADE)
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                        "-vf", f"fade=t=in:st=0:d={FADE},fade=t=out:st={out:.2f}:d={FADE}",
                        "-af", f"afade=t=in:st=0:d={FADE},afade=t=out:st={out:.2f}:d={FADE}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30",
                        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "1", dst])
    if r.returncode:
        raise RuntimeError("ffmpeg fade failed")


def make_relax(total_min, out_path, seed=None, verbose=True, scene_range=(180, 300)):
    rng = random.Random(seed)
    work = out_path[:-4] + "_scenes"
    os.makedirs(work, exist_ok=True)
    remaining, used, parts, scenes = total_min * 60.0, [], [], []
    while remaining > 45:
        lo, hi = scene_range
        sec = min(remaining, rng.uniform(lo, hi)) if remaining > hi * 1.2 else remaining
        cfg = scene_cfg(rng, round(sec), used)
        raw = os.path.join(work, f"raw_{len(parts):02d}.mp4")
        if verbose:
            print(f"scene {len(parts) + 1}: {cfg['pattern']}/{cfg['obstacle']}/{cfg['palette']} ~{sec / 60:.1f} min")
        meta = gen.make_video(cfg, raw, verbose=verbose)
        faded = os.path.join(work, f"scene_{len(parts):02d}.mp4")
        fade(raw, faded, meta["duration"])
        os.remove(raw)
        parts.append(faded)
        used.append(cfg["pattern"])
        scenes.append(dict(pattern=cfg["pattern"], obstacle=cfg["obstacle"], palette=cfg["palette"],
                           seconds=meta["duration"], bricks=meta["bricks"]))
        remaining -= meta["duration"]
    lst = os.path.join(work, "list.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.abspath(p)}'\n" for p in parts)
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
                        "-movflags", "+faststart", out_path])
    if r.returncode:
        raise RuntimeError("ffmpeg concat failed")
    for p in parts + [lst]:
        os.remove(p)
    os.rmdir(work)
    total = sum(s["seconds"] for s in scenes)
    if verbose:
        print(f"wrote {out_path}: {total / 60:.1f} min, {len(scenes)} scenes")
    return dict(file=out_path, duration=total, scenes=scenes)


# ------------------------------------------------------------------ publishing
TITLES = ["{len} of Oddly Satisfying Brick Breaking 😴 Relax, Study, Sleep",
          "{len} of Calm Brick Breaking for Sleep & Focus 🌙",
          "Relaxing Brick Breaker for {len} 😌 No Talking, Soft Sounds",
          "{len} of Satisfying Bricks to Fall Asleep To 💤",
          "Study With Me: {len} of Calm Brick Breaking 📚"]


def length_label(sec):
    m = round(sec / 60)
    return "1 Hour" if 55 <= m <= 65 else f"{m // 60} Hours" if m >= 110 and m % 60 < 6 else f"{m} Minutes"


def volume_number():
    path = os.path.join(HERE, "data", "posts.csv")
    if not os.path.exists(path):
        return 1
    with open(path, newline="") as f:
        return 1 + sum(1 for r in csv.DictReader(f) if r.get("pattern") == "relax")


def captions(meta, vol, cfg, rng):
    label = length_label(meta["duration"])
    title = rng.choice(TITLES).format(len=label)
    tags = cfg["youtube"].get("hashtags_by_style", {}).get("relax", ["#relaxing", "#satisfying", "#sleep"])
    chapters, t = [], 0.0
    for i, s in enumerate(meta["scenes"]):
        mm, ss = divmod(int(t), 60)
        hh, mm = divmod(mm, 60)
        stamp = f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm}:{ss:02d}"
        shape = {"solid": "wall", "checker": "checkerboard"}.get(s["pattern"], s["pattern"])
        chapters.append(f"{stamp} Scene {i + 1}: {shape}")
        t += s["seconds"]
    desc = "\n".join([f"Relax Vol. {vol}: {label.lower()} of calm, oddly satisfying brick breaking. Soft sounds, no "
                      "talking, no ads in the middle of the action. Put it on while you study, work or fall asleep.",
                      "", *chapters, "", "New relaxing videos every week. Subscribe for more 🧱", "", " ".join(tags)])
    return {"title": title[:100], "description": desc, "tags": cfg["youtube"]["tags"] + ["relaxing", "sleep",
                                                                                           "study", "asmr", "calm"],
            "playlist": cfg["youtube"].get("playlists", {}).get("relax"),
            "comment": "What are you listening to this for: studying, working or sleeping? 😴"}


def thumbnail(video, out, label):
    """1280x720: a calm mid-video frame, soft vignette, big '1 HOUR' + 'RELAX · STUDY · SLEEP'."""
    still = out[:-4] + "_frame.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "12", "-i", video, "-frames:v", "1", still],
                   check=True)
    img = Image.open(still).convert("RGB").resize((1280, 720), Image.LANCZOS)
    os.remove(still)
    shade = Image.new("L", (1280, 720))
    d = ImageDraw.Draw(shade)
    for y in range(720):
        d.line((0, y, 1280, y), fill=int(170 * max(0.0, (y - 300) / 420)))
    img = Image.composite(Image.new("RGB", (1280, 720), (6, 6, 12)), img, shade)
    d = ImageDraw.Draw(img)
    big = label.upper()
    size = 150
    while gen.font(size).getlength(big) > 1180 and size > 60:
        size -= 4
    d.text((640, 545), big, font=gen.font(size), fill=(255, 255, 255), anchor="ms", stroke_width=8,
           stroke_fill=(10, 10, 16))
    d.text((640, 640), "RELAX · STUDY · SLEEP", font=gen.font(54), fill=(170, 200, 255), anchor="ms",
           stroke_width=5, stroke_fill=(10, 10, 16))
    img.filter(ImageFilter.UnsharpMask(radius=2, percent=50)).save(out, "JPEG", quality=90)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--out", default="relax.mp4")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--scene-sec", default="180,300", help="min,max scene length in seconds")
    a = ap.parse_args()
    live = a.live or os.environ.get("AUTOPOST_LIVE", "").lower() in ("1", "true", "yes")
    import pipeline
    cfg = pipeline.load_config(os.path.join(HERE, "config.json"))
    rng = random.Random(a.seed)
    meta = make_relax(a.minutes, a.out, seed=rng.randint(1, 10 ** 6),
                      scene_range=tuple(float(x) for x in a.scene_sec.split(",")))
    vol = volume_number()
    cap = captions(meta, vol, cfg, rng)
    thumb = thumbnail(a.out, a.out[:-4] + "_thumb.jpg", length_label(meta["duration"]))
    print(f"title: {cap['title']}\n{cap['description']}\nthumbnail: {thumb}")
    lines = [f"## Relax video ({'LIVE' if live else 'DRY RUN'})", f"{cap['title']} ({meta['duration'] / 60:.1f} min, "
             f"{len(meta['scenes'])} scenes)"]
    if live:
        from publishers import youtube
        url = youtube.post(a.out, cap, cfg.get("youtube", {})).replace("/shorts/", "/watch?v=")
        print(f"posted: {url}")
        lines.append(f"Posted: {url}")
        try:
            youtube.set_thumbnail(url.split("v=")[-1], thumb)
            print("thumbnail set")
        except Exception as e:
            print(f"thumbnail skipped: {e}")
        v = dict(file=a.out, pattern="relax", obstacle=f"{len(meta['scenes'])} scenes", palette="relax",
                 duration=meta["duration"], outcome="", cleared_pct="", bricks=sum(s["bricks"] for s in meta["scenes"]),
                 start_balls="", bonus_every="", peak_balls="")
        pipeline.append_post_log([{"video": v, "captions": {"x": {"hook": f"Relax Vol. {vol}", "hashtags": False}},
                                   "posts": {"youtube": {"url": url}}}], "")
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a") as f:
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
