#!/usr/bin/env python3
"""
Weekly-episode thumbnails (1280x720 JPEG): a fresh widescreen color-battle frame mid-race, darkened on the left,
with big bold text ("WHO WINS?"), the matchup in team colors, and an EPISODE badge. Needs a phone-verified channel.

  python3 thumbnail.py --episode 1 --out thumb.jpg              # just make the image
  python3 thumbnail.py --episode 1 --set VIDEO_ID               # make it and set it on that YouTube video
"""
import argparse
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle  # noqa: E402
import brick_breaker_gen as gen  # noqa: E402

TW, TH = 1280, 720
HEADLINES = ["WHO WINS?", "PICK A SIDE", "SO CLOSE!"]


def battle_frame(seed, teams, workdir):
    battle.configure(1920, 1080)
    cfg = dict(seed=seed, target=30, teams=teams, outdir=workdir)
    paths = battle.make_battle(cfg, preview=[15], verbose=False)  # mid-race: lots of bricks gone, balls flying
    im = Image.open(paths[0]).convert("RGB")
    return im.crop((0, 0, 1920, 940))  # zoom past the empty floor area


def text_stroked(d, xy, txt, font, fill, stroke=8, anchor="la"):
    d.text(xy, txt, font=font, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=(10, 10, 14))


def make_thumbnail(out_path, episode, seed=None, rounds=None):
    rng = random.Random(seed if seed is not None else episode * 977)
    teams = ("RED", "BLUE") if rng.random() < 0.6 else tuple(rng.sample(list(battle.TEAMS), 2))
    workdir = os.path.dirname(os.path.abspath(out_path)) or "."
    img = battle_frame(rng.randint(1, 10 ** 6), teams, workdir).resize((TW, TH), Image.LANCZOS)
    # darken the left side so the text pops, keep the race visible on the right
    shade = Image.new("L", (TW, TH))
    sd = ImageDraw.Draw(shade)
    for x in range(TW):
        sd.line((x, 0, x, TH), fill=int(205 * max(0.0, 1 - x / (TW * 0.62))))
    img = Image.composite(Image.new("RGB", (TW, TH), (8, 8, 12)), img, shade)
    d = ImageDraw.Draw(img)
    head = rng.choice(HEADLINES)
    size = 170
    while gen.font(size).getlength(head) > TW * 0.62 and size > 60:
        size -= 4
    text_stroked(d, (56, 215), head, gen.font(size), (255, 255, 255), stroke=9)
    a, b = teams
    ca, cb = battle.TEAMS[a][1], battle.TEAMS[b][1]
    f2 = gen.font(84)
    x = 60
    for word, col in ((a, ca), (" vs ", (235, 235, 240)), (b, cb)):
        text_stroked(d, (x, 215 + size + 40), word, f2, col, stroke=7)
        x += f2.getlength(word)
    # episode badge (yellow pill) + round count
    badge = f"EPISODE {episode}"
    fb = gen.font(52)
    bw = fb.getlength(badge) + 56
    d.rounded_rectangle((52, 70, 52 + bw, 150), radius=40, fill=(255, 205, 40))
    d.text((52 + bw / 2, 110), badge, font=fb, fill=(15, 15, 20), anchor="mm")
    if rounds:
        text_stroked(d, (60, TH - 70), f"{rounds} ROUNDS · BATTLES · ESCAPES · DROPS", gen.font(36),
                     (210, 210, 220), stroke=5, anchor="ls")
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=60))
    img.save(out_path, "JPEG", quality=90)
    for p in os.listdir(workdir):  # tidy the preview still
        if p.startswith("battle_") and p.endswith(".jpg"):
            os.remove(os.path.join(workdir, p))
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--rounds", type=int, default=None)
    ap.add_argument("--out", default="thumb.jpg")
    ap.add_argument("--set", default="", help="YouTube video id to set the thumbnail on")
    a = ap.parse_args()
    make_thumbnail(a.out, a.episode, rounds=a.rounds)
    print(f"thumbnail: {a.out}")
    if a.set:
        from publishers import youtube
        youtube.set_thumbnail(a.set.strip(), a.out)
        print(f"set thumbnail on https://youtube.com/watch?v={a.set.strip()}")


if __name__ == "__main__":
    main()
