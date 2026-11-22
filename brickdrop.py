#!/usr/bin/env python3
"""
Brick Drop: white balls drop from random spots across the top of a board of peg-bricks (each takes several hits,
cracks, then shatters, so the paths change as it goes) into 4 color bins. The color with the most balls wins.
Seeds are simulated headlessly first; the one with the closest finish (and most lead changes) is rendered.
(Don't call it "Plinko" anywhere - that's a trademarked game-show name.)

  python3 brickdrop.py --target 25 --out drop.mp4
"""
import argparse
import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw

import brick_breaker_gen as gen
from sfx import SR, Encoder, add, bell, mux, noise_burst, win_chime, write_wav

W, H, FPS, SUB = 1080, 1920, 30, 4
X0, X1 = 150, 930                     # inside the phone-crop safe area
TOP, PEG_TOP, BIN_TOP, FLOOR = 250, 380, 1390, 1700
NB, R, PR, G = 4, 13, 14, 1500.0
GAP = 70
TEAMS = [("RED", (235, 70, 70)), ("YELLOW", (245, 200, 40)), ("BLUE", (60, 130, 245)), ("GREEN", (50, 185, 95))]
BW = (X1 - X0) / NB


class Run:
    def __init__(self, seed, balls, every, hp):
        self.rng = random.Random(seed)
        self.balls_total, self.every = balls, every
        self.rows = int((BIN_TOP - 70 - PEG_TOP) / GAP)
        self.pegs = []
        for r in range(self.rows):
            x = X0 + 35 + (0 if r % 2 == 0 else GAP / 2)
            while x < X1 - 30:
                self.pegs.append(dict(x=x, y=PEG_TOP + r * GAP, hp=hp, hp0=hp, row=r, alive=True))
                x += GAP
        self.grid = {}
        for i, p in enumerate(self.pegs):
            self.grid.setdefault((int(p["x"] // 80), int(p["y"] // 80)), []).append(i)
        self.bins = [0] * NB
        self.balls, self.shards, self.events = [], [], []
        self.dropped, self.frame, self.end, self.leader, self.changes = 0, 0, None, None, 0
        self.scale = max(2.0, min(6.0, 260 / max(1, balls / NB * 1.25)))   # px of bin fill per ball

    def step(self):
        rng = self.rng
        if self.dropped < self.balls_total and self.frame / FPS >= self.dropped * self.every:
            self.balls.append([rng.uniform(X0 + 50, X1 - 50), TOP, rng.uniform(-40, 40), 0.0])
            self.dropped += 1
        dt = 1 / FPS / SUB
        for _ in range(SUB):
            keep = []
            for b in self.balls:
                b[3] += G * dt
                b[0] += b[2] * dt
                b[1] += b[3] * dt
                if abs(b[2]) + abs(b[3]) < 40 and b[1] < BIN_TOP:   # balanced on a peg: nudge it off
                    b[2] += rng.choice((-1, 1)) * 120
                if b[0] < X0 + R:
                    b[0], b[2] = X0 + R, abs(b[2]) * 0.6
                if b[0] > X1 - R:
                    b[0], b[2] = X1 - R, -abs(b[2]) * 0.6
                gx, gy = int(b[0] // 80), int(b[1] // 80)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for i in self.grid.get((gx + dx, gy + dy), ()):
                            p = self.pegs[i]
                            if not p["alive"]:
                                continue
                            ex, ey = b[0] - p["x"], b[1] - p["y"]
                            d = math.hypot(ex, ey)
                            if 0 < d < R + PR:
                                nx, ny = ex / d, ey / d
                                vn = b[2] * nx + b[3] * ny
                                if vn < 0:
                                    b[2] -= 1.55 * vn * nx
                                    b[3] -= 1.55 * vn * ny
                                    b[2] += rng.uniform(-25, 25)
                                    if -vn > 260:
                                        p["hp"] -= 1
                                        self.events.append((self.frame, "tick", p["row"]))
                                        if p["hp"] <= 0:
                                            p["alive"] = False
                                            self.events.append((self.frame, "break", p["row"]))
                                            col = gen.hsv(p["row"] / self.rows * 0.8, 0.7, 0.95)
                                            for _k in range(6):
                                                a = rng.uniform(0, 6.28)
                                                self.shards.append([p["x"], p["y"], math.cos(a) * 160,
                                                                    math.sin(a) * 160 - 120, 1.0, col])
                                b[0], b[1] = p["x"] + nx * (R + PR), p["y"] + ny * (R + PR)
                for k in range(1, NB):
                    wx = X0 + k * BW
                    if b[1] > BIN_TOP and abs(b[0] - wx) < R + 4:
                        b[0] = wx + (R + 4) * (1 if b[0] > wx else -1)
                        b[2] = -b[2] * 0.4
                k = min(NB - 1, max(0, int((b[0] - X0) // BW)))
                if b[1] > FLOOR - 40 - self.bins[k] * self.scale:
                    self.bins[k] += 1
                    self.events.append((self.frame, "land", k))
                    lead = max(range(NB), key=lambda j: self.bins[j])
                    if self.bins.count(self.bins[lead]) == 1 and lead != self.leader:
                        if self.leader is not None:
                            self.changes += 1
                        self.leader = lead
                else:
                    keep.append(b)
            self.balls = keep
        if self.dropped == self.balls_total and not self.balls and self.end is None:
            self.end = self.frame
        self.frame += 1


def choose(cfg, verbose=True):
    """Balls/drop rate from the target length; then the seed with the closest finish and most lead changes."""
    target = cfg["target"]
    every = 0.18
    balls = int(max(40, min(160, (target - 4) / every)))
    hp = max(4, min(10, round(balls / 13)))
    best = None
    for s in range(cfg["seed"], cfg["seed"] + 14):
        r = Run(s, balls, every, hp)
        while r.end is None and r.frame < FPS * 90:
            r.step()
        if r.end is None:
            continue
        top = sorted(r.bins)
        margin = top[-1] - top[-2]
        if margin == 0:
            continue  # ties don't make a winner
        score = margin * 2 - min(r.changes, 8) + abs(r.end / FPS - target) / 3
        if best is None or score < best[0]:
            best = (score, s, r.end, margin, r.changes)
        if margin == 1 and r.changes >= 5:
            break
    limit = cfg.get("reject_over")
    if best is None or (limit and best[2] / FPS > limit):
        raise gen.TooLong(f"no drop near {target:.0f}s")
    if verbose:
        print(f"  drop: {balls} balls, peg hp {hp}, seed {best[1]} -> ends {best[2] / FPS:.1f}s, "
              f"won by {best[3]}, {best[4]} lead change(s) (target {target:.0f}s)")
    return best[1], balls, every, hp


def end_card(name, col, bins, extras):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bw, bh = int(W * 0.8), int(H * 0.17)
    x0, y0 = (W - bw) // 2, int(H * 0.36)
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=40, fill=(10, 10, 14, 235))
    head = f"{name} WINS!"
    size = int(W * 0.095)
    while gen.font(size).getlength(head) > bw * 0.9:
        size -= 2
    d.text((W / 2, y0 + bh * 0.14), head, font=gen.font(size), fill=col, anchor="mt", stroke_width=3,
           stroke_fill=(20, 20, 26))
    top = sorted(bins)
    d.text((W / 2, y0 + bh * 0.66), f"{top[-1]} balls to {top[-2]}", font=gen.font(int(W * 0.05)),
           fill=(225, 225, 235), anchor="mt")
    gen.draw_card_extras(d, W, y0 + bh + int(W * 0.04), extras, winner=name)
    arr = np.array(img).astype(np.float32)
    return arr[..., :3], arr[..., 3:] / 255.0


def make_brick_drop(cfg, out_path, verbose=True):
    """cfg: seed, target, [reject_over], [card_extras]. Returns metadata like make_video()."""
    seed, balls, every, hp = choose(cfg, verbose)
    run = Run(seed, balls, every, hp)
    tmp_v, tmp_a = out_path[:-4] + ".v.tmp.mp4", out_path[:-4] + ".a.tmp.wav"
    enc = Encoder(tmp_v)
    bg = np.zeros((H, W, 3), np.uint8)
    bg[:] = (14, 14, 20)
    f_mid, f_small = gen.font(52), gen.font(40)
    card, after = None, 0
    while run.frame < FPS * 120:
        run.step()
        img = Image.fromarray(bg.copy())
        d = ImageDraw.Draw(img)
        for k in range(NB):
            x0 = X0 + k * BW
            name, col = TEAMS[k]
            d.rectangle((x0 + 6, FLOOR - run.bins[k] * run.scale, x0 + BW - 6, FLOOR),
                        fill=tuple(int(v * 0.8) for v in col))
            d.rectangle((x0 + 6, BIN_TOP, x0 + BW - 6, FLOOR), outline=(60, 60, 72), width=3)
            d.text((x0 + BW / 2, FLOOR + 50), name, font=f_small, fill=col, anchor="mm")
            d.text((x0 + BW / 2, BIN_TOP - 40), str(run.bins[k]), font=f_mid, fill=(235, 235, 245), anchor="mm")
        wall = (120, 122, 132)
        for k in range(1, NB):
            wx = X0 + k * BW
            d.rectangle((wx - 4, BIN_TOP, wx + 4, FLOOR), fill=wall)
        d.rectangle((X0 - 10, TOP - 60, X0, FLOOR), fill=wall)
        d.rectangle((X1, TOP - 60, X1 + 10, FLOOR), fill=wall)
        d.rectangle((X0 - 10, FLOOR, X1 + 10, FLOOR + 10), fill=wall)
        for p in run.pegs:
            if not p["alive"]:
                continue
            c = gen.hsv(p["row"] / run.rows * 0.8, 0.7, 0.95 * (0.5 + 0.5 * p["hp"] / p["hp0"]))
            d.rectangle((p["x"] - PR, p["y"] - PR, p["x"] + PR, p["y"] + PR), fill=tuple(int(v * 0.55) for v in c))
            d.rectangle((p["x"] - PR + 2, p["y"] - PR + 2, p["x"] + PR - 2, p["y"] + PR - 2), fill=c)
            if p["hp"] < p["hp0"] * 0.6:   # crack
                d.line((p["x"] - 6, p["y"] - 7, p["x"] + 2, p["y"] + 1, p["x"] - 1, p["y"] + 8), fill=(20, 20, 26),
                       width=2)
        keep = []
        for s in run.shards:
            s[3] += 900 / FPS
            s[0] += s[2] / FPS
            s[1] += s[3] / FPS
            s[4] -= 0.04
            if s[4] > 0:
                keep.append(s)
                c = tuple(int(v * s[4] + 14 * (1 - s[4])) for v in s[5])
                d.rectangle((s[0] - 5, s[1] - 5, s[0] + 5, s[1] + 5), fill=c)
        run.shards = keep
        for b in run.balls:
            d.ellipse((b[0] - R, b[1] - R, b[0] + R, b[1] + R), fill=(250, 250, 250))
        f = np.array(img)
        if run.end is not None:
            if card is None:
                win = max(range(NB), key=lambda j: run.bins[j])
                card = end_card(TEAMS[win][0], TEAMS[win][1], run.bins, cfg.get("card_extras"))
            a = min(1.0, after / 8)
            f = (f.astype(np.float32) * (1 - card[1] * a) + card[0] * card[1] * a).astype(np.uint8)
            after += 1
            if after > 2.5 * FPS:
                break
        enc.write(f)
    enc.close()
    mix = np.zeros(int(enc.n / FPS * SR) + SR, np.float32)
    pent = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21, 24, 26, 28]
    last_tick = -1.0
    for fr, kind, k in run.events:
        i, tt = int(fr / FPS * SR), fr / FPS
        if kind == "tick":
            if tt - last_tick < 0.025:
                continue
            last_tick = tt
            add(mix, i, bell(880 * 2 ** (pent[(run.rows - 1 - k) % len(pent)] / 12), 0.12, 0.09, 30))
        elif kind == "break":
            add(mix, i, noise_burst(0.18, 0.12, 25, fr))
        else:
            add(mix, i, bell(196 * 2 ** ([0, 4, 7, 12][k] / 12), 0.4, 0.25, 8))
    if run.end is not None:
        win_chime(mix, run.end / FPS)
    write_wav(tmp_a, mix)
    mux(tmp_v, tmp_a, out_path)
    os.remove(tmp_v)
    os.remove(tmp_a)
    win = max(range(NB), key=lambda j: run.bins[j])
    top = sorted(run.bins)
    meta = dict(file=out_path, mode="drop", title="Brick Drop", seed=seed, pattern=f"drop-{balls}", obstacle="pegs",
                palette="drop-4bins", duration=round(enc.n / FPS, 2), bricks=len(run.pegs),
                outcome=f"{TEAMS[win][0].lower()} wins", cleared_pct=100,
                clear_time=round((run.end or run.frame) / FPS, 1), start_balls=balls, bonus_every=0, peak_balls=balls,
                balls_lost=0, teams=[t[0] for t in TEAMS], winner=TEAMS[win][0], margin=top[-1] - top[-2],
                margin_s=top[-1] - top[-2], lead_changes=run.changes, bins=list(run.bins))
    if verbose:
        print(f"  wrote {out_path}  ({enc.n / FPS:.1f}s, {TEAMS[win][0]} wins {top[-1]}-{top[-2]}, "
              f"{run.changes} lead change(s))")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=float, default=25)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default="drop.mp4")
    a = ap.parse_args()
    make_brick_drop(dict(seed=a.seed if a.seed is not None else random.randint(1, 10 ** 6), target=a.target), a.out)


if __name__ == "__main__":
    main()
