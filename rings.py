#!/usr/bin/env python3
"""
Ring Escape: one ball bounces (with gravity) inside 6-8 spinning rings of bricks. Each ring has a gap; when the
ball slips through, that ring shatters. Escape every ring to win. Notes rise as the ball gets further out.

Seeds are simulated headlessly first and the one whose escape time lands closest to the target length is
rendered (pipeline re-rolls via gen.TooLong if none fits).

  python3 rings.py --target 25 --out rings.mp4
"""
import argparse
import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw

import brick_breaker_gen as gen
from sfx import SR, Encoder, add, bell, mux, noise_burst, win_chime, write_wav

W, H, FPS, SUB = 1080, 1920, 30, 6
CX, CY = W / 2, H * 0.47
GRAV = 950.0


def configure(w, h):
    """Switch canvas size, e.g. configure(1920, 1080) for the widescreen weekly episode."""
    global W, H, CX, CY
    W, H = w, h
    CX, CY = W / 2, H * (0.47 if H > W else 0.5)
BALL_R = 15


def make_rings(rng):
    n = rng.choice([7, 8, 8, 9])
    hue0 = rng.random()
    gap = math.radians(rng.uniform(44, 56))
    rings = []
    for i in range(n):
        R = 95 + i * (300 / max(1, n - 1))
        rings.append(dict(R=R, n=int(2 * math.pi * R / 26), rot=rng.uniform(0, 6.28),
                          spd=(0.9 + 0.12 * i) * (1 if (i % 2) else -1) * rng.uniform(0.85, 1.15),
                          gap=gap, alive=True, color=gen.hsv((hue0 + i / n * 0.85) % 1, 0.75, 0.95)))
    return rings


def in_gap(a, ring):
    return (a - ring["rot"]) % (2 * math.pi) < ring["gap"]


class Run:
    """Deterministic physics for one seed; step() advances one video frame."""
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.rings = make_rings(self.rng)
        self.ball = [CX, CY, self.rng.uniform(-260, 260), -380.0]
        self.frame, self.events, self.shards, self.end = 0, [], [], None

    def step(self):
        rng, b = self.rng, self.ball
        dt = 1 / FPS / SUB
        for _ in range(SUB):
            b[3] += GRAV * dt
            b[0] += b[2] * dt
            b[1] += b[3] * dt
            dx, dy = b[0] - CX, b[1] - CY
            dist = math.hypot(dx, dy) or 1
            k = next((i for i, r in enumerate(self.rings) if r["alive"]), None)
            if k is None:
                break
            rg = self.rings[k]
            if dist + BALL_R <= rg["R"] - 10:
                continue
            if dist > rg["R"] + 14:          # out through the gap -> shatter the ring
                rg["alive"] = False
                self.events.append((self.frame, "break", k))
                for j in range(rg["n"]):
                    t = rg["rot"] + j / rg["n"] * 2 * math.pi
                    if in_gap(t, rg):
                        continue
                    sp = rng.uniform(150, 420)
                    self.shards.append([CX + rg["R"] * math.cos(t), CY + rg["R"] * math.sin(t),
                                        math.cos(t) * sp + rng.uniform(-60, 60),
                                        math.sin(t) * sp - rng.uniform(0, 200), 1.0, rg["color"]])
                if all(not r["alive"] for r in self.rings):
                    self.end = self.frame
            elif not in_gap(math.atan2(dy, dx), rg):
                nx, ny = dx / dist, dy / dist
                vn = b[2] * nx + b[3] * ny
                if vn > 0:
                    b[2] -= 2 * vn * nx
                    b[3] -= 2 * vn * ny
                    sp = math.hypot(b[2], b[3]) or 1
                    want = max(sp, 720)
                    b[2] *= want / sp
                    b[3] *= want / sp
                    b[2] += rng.uniform(-40, 40)
                    self.events.append((self.frame, "bounce", k))
                over = dist + BALL_R - (rg["R"] - 10)
                if over > 0:
                    b[0] -= nx * over
                    b[1] -= ny * over
        for r in self.rings:
            r["rot"] += r["spd"] / FPS
        self.frame += 1


def probe(seed, cap):
    r = Run(seed)
    while r.end is None and r.frame < cap:
        r.step()
    return r.end


def choose(cfg, verbose=True):
    # ring escapes are naturally quick: aim for 12-30 s whatever the general length target is
    target, best = min(max(cfg["target"], 12), 30), None
    for s in range(cfg["seed"], cfg["seed"] + 24):
        end = probe(s, int(target * FPS * 1.6))
        if end is None:
            continue
        err = abs(end / FPS - target)
        if best is None or err < best[0]:
            best = (err, s, end)
        if err < 1.5:
            break
    limit = cfg.get("reject_over")
    if best is None or (limit and best[2] / FPS > limit) or best[2] / FPS < target * 0.6:
        raise gen.TooLong(f"no ring layout near {target:.0f}s")
    if verbose:
        print(f"  rings: seed {best[1]} escapes at {best[2] / FPS:.1f}s (target {target:.0f}s)")
    return best[1]


def end_card(secs, n, extras):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    base = min(W, H * 0.5625)          # card sized like a phone-width card, also in widescreen
    bw, bh = int(base * 0.8), int(base * 0.3)
    x0, y0 = (W - bw) // 2, (H - bh) // 2
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=40, fill=(10, 10, 14, 235))
    d.text((W / 2, y0 + bh * 0.14), "ESCAPED!", font=gen.font(int(base * 0.105)), fill=(255, 255, 255), anchor="mt")
    d.text((W / 2, y0 + bh * 0.66), f"{n} rings in {secs}s", font=gen.font(int(base * 0.05)), fill=(255, 200, 90),
           anchor="mt")
    gen.draw_card_extras(d, W, y0 + bh + int(base * 0.04), extras)
    arr = np.array(img).astype(np.float32)
    return arr[..., :3], arr[..., 3:] / 255.0


def make_ring_escape(cfg, out_path, verbose=True):
    """cfg: seed, target, [reject_over], [card_extras]. Returns metadata like make_video()."""
    seed = choose(cfg, verbose)
    run = Run(seed)
    n = len(run.rings)
    tmp_v, tmp_a = out_path[:-4] + ".v.tmp.mp4", out_path[:-4] + ".a.tmp.wav"
    enc = Encoder(tmp_v, W, H)
    bg = np.zeros((H, W, 3), np.uint8)
    bg[:] = (14, 14, 20)
    trail, card, after = [], None, 0
    cap = int(cfg.get("max_len", 90) * FPS)
    while run.frame < cap:
        run.step()
        img = Image.fromarray(bg.copy())
        d = ImageDraw.Draw(img)
        for rg in run.rings:
            if not rg["alive"]:
                continue
            for j in range(rg["n"]):
                t = rg["rot"] + (j + 0.5) / rg["n"] * 2 * math.pi
                if in_gap(t, rg):
                    continue
                px, py = CX + rg["R"] * math.cos(t), CY + rg["R"] * math.sin(t)
                dark = tuple(int(v * 0.55) for v in rg["color"])
                d.rectangle((px - 11, py - 11, px + 11, py + 11), fill=dark)
                d.rectangle((px - 9, py - 9, px + 9, py + 9), fill=rg["color"])
        keep = []
        for s in run.shards:
            s[3] += GRAV / FPS * 0.9
            s[0] += s[2] / FPS
            s[1] += s[3] / FPS
            s[4] -= 0.025
            if s[4] > 0 and s[1] < H:
                keep.append(s)
                c = tuple(int(v * s[4] + 14 * (1 - s[4])) for v in s[5])
                d.rectangle((s[0] - 8, s[1] - 8, s[0] + 8, s[1] + 8), fill=c)
        run.shards = keep
        b = run.ball
        trail = (trail + [(b[0], b[1])])[-5:]
        for k, (tx, ty) in enumerate(trail[:-1]):
            a, r = 0.15 + 0.12 * k, BALL_R * (0.6 + 0.08 * k)
            cc = int(14 + 241 * a)
            d.ellipse((tx - r, ty - r, tx + r, ty + r), fill=(cc, cc, cc))
        d.ellipse((b[0] - BALL_R, b[1] - BALL_R, b[0] + BALL_R, b[1] + BALL_R), fill=(255, 255, 255))
        f = np.array(img)
        if run.end is not None:
            if card is None:
                card = end_card(run.end // FPS, n, cfg.get("card_extras"))
            a = min(1.0, after / 8)
            f = (f.astype(np.float32) * (1 - card[1] * a) + card[0] * card[1] * a).astype(np.uint8)
            after += 1
            if after > 2.5 * FPS:
                break
        enc.write(f)
    enc.close()
    mix = np.zeros(int(enc.n / FPS * SR) + SR, np.float32)
    scale = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21, 24]
    for fr, kind, k in run.events:
        i = int(fr / FPS * SR)
        if kind == "bounce":
            add(mix, i, bell(262 * 2 ** (scale[k % len(scale)] / 12), 0.35, 0.22, 9))
        else:
            for j, st in enumerate((0, 4, 7, 12)):
                add(mix, i + int(j * 0.04 * SR), bell(523 * 2 ** ((scale[k % len(scale)] + st) / 12), 0.6, 0.16, 6))
            add(mix, i, noise_burst(0.25, 0.08, 18, fr))
    if run.end is not None:
        win_chime(mix, run.end / FPS)
    write_wav(tmp_a, mix)
    mux(tmp_v, tmp_a, out_path)
    os.remove(tmp_v)
    os.remove(tmp_a)
    secs = round((run.end if run.end is not None else run.frame) / FPS, 1)
    meta = dict(file=out_path, mode="rings", title="Ring Escape", seed=seed, pattern=f"rings-{n}", obstacle="none",
                palette=f"rings-{n}", duration=round(enc.n / FPS, 2), bricks=sum(r["n"] for r in run.rings),
                outcome="escaped" if run.end is not None else "timeout", cleared_pct=100, clear_time=secs,
                start_balls=1, bonus_every=0, peak_balls=1, balls_lost=0, rings=n)
    if verbose:
        print(f"  wrote {out_path}  ({enc.n / FPS:.1f}s, {n} rings, escaped at {secs}s)")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=float, default=25)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default="rings.mp4")
    a = ap.parse_args()
    make_ring_escape(dict(seed=a.seed if a.seed is not None else random.randint(1, 10 ** 6), target=a.target), a.out)


if __name__ == "__main__":
    main()
