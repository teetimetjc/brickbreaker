#!/usr/bin/env python3
"""
Brick Escape: four colored balls (RED, YELLOW, BLUE, GREEN) start at the bottom of a tall course and race
up through layers of brick walls. Neutral bricks break for anyone; team-colored bricks only break for the
ball of that color (they are solid walls to everyone else). Balls bump into each other. The first ball to
reach the checkered line at the top escapes and wins.

Like color battles, the race is tuned before rendering: many bounce-seeds are simulated headlessly and the
one with the closest finish and the most lead changes (near the target length) is rendered. Winner is random.
Two looks: theme "dark" (matches the other videos) or "light" (stands out in a dark feed).

  python3 escape.py --target 40 --theme light --out escape.mp4
  python3 escape.py --preview 3,15 --theme dark --seed 4
"""
import argparse
import math
import os
import random
import subprocess

import numpy as np
from PIL import Image, ImageDraw

import brick_breaker_gen as gen
from brick_breaker_gen import FPS

W, H = 1080, 1920
CELL = 26
M_SIDE, M_TOP, M_BOT = int(W * 0.115), int(H * 0.05), int(H * 0.06)
COLS = (W - 2 * M_SIDE) // CELL
ROWS = (H - M_TOP - M_BOT) // CELL
OX = (W - COLS * CELL) // 2
OY = M_TOP + (H - M_TOP - M_BOT - ROWS * CELL) // 2
LAYER_OPTIONS = [5, 6, 7, 8]


def configure(w, h):
    """Switch canvas size, e.g. configure(1920, 1080) for widescreen compilations. Default is 1080x1920."""
    global W, H, M_SIDE, M_TOP, M_BOT, COLS, ROWS, OX, OY, LAYER_OPTIONS
    W, H = w, h
    if h > w:
        M_SIDE, M_TOP, M_BOT = int(w * 0.115), int(h * 0.05), int(h * 0.06)
        LAYER_OPTIONS = [5, 6, 7, 8]
    else:  # wide and short course: fewer layers fit
        M_SIDE, M_TOP, M_BOT = int(w * 0.03), int(h * 0.04), int(h * 0.04)
        LAYER_OPTIONS = [3, 4, 5]
    COLS = (W - 2 * M_SIDE) // CELL
    ROWS = (H - M_TOP - M_BOT) // CELL
    OX = (W - COLS * CELL) // 2
    OY = M_TOP + (H - M_TOP - M_BOT - ROWS * CELL) // 2
    _AudioLayout.brick_bot = ROWS - 9
R_BALL = 0.8  # ball radius in cells
LIFT = 0.06  # gentle upward pull per frame (as a fraction of speed): balls rise like bubbles

EMPTY, WALL, BRICK, FINISH = 0, 1, 2, 3
TEAM0 = 10  # team bricks: TEAM0 + team index

TEAMS = [("RED", (235, 70, 70)), ("YELLOW", (245, 200, 40)), ("BLUE", (60, 130, 245)), ("GREEN", (50, 185, 95))]

THEMES = {
    "dark": dict(bg=(14, 14, 20), wall=(120, 122, 132), wall_edge=(78, 80, 90), brick=(150, 110, 230),
                 brick2=(95, 60, 175), text=(240, 240, 248), card=(10, 10, 14, 235), sub=(220, 220, 232)),
    "light": dict(bg=(236, 234, 228), wall=(150, 152, 160), wall_edge=(110, 112, 122), brick=(52, 56, 72),
                  brick2=(28, 30, 40), text=(30, 32, 40), card=(250, 250, 248, 240), sub=(70, 72, 84)),
}


# --------------------------------------------------------------------------- course
def build_course(seed, layers):
    """Grid of the course: start chamber at the bottom, `layers` brick barriers, finish line on top."""
    rng = random.Random(seed)
    g = np.zeros((ROWS, COLS), np.int16)
    hp = np.zeros((ROWS, COLS), np.int16)
    g[0, :] = g[-1, :] = WALL
    g[:, 0] = g[:, -1] = WALL
    finish_row = 3
    g[1:finish_row, 1:-1] = FINISH
    start_top = ROWS - 9  # start chamber: rows start_top..ROWS-2
    span = start_top - (finish_row + 3)
    gap = span / layers
    for k in range(layers):
        y = int(finish_row + 3 + gap * (k + 0.5))
        thick = rng.choice([1, 2, 2])
        x = 1
        segs = []
        while x < COLS - 1:
            w = rng.randint(3, 7)
            segs.append([x, min(COLS - 1, x + w)])
            x += w
        kinds = []
        for i in range(len(segs)):
            r = rng.random()
            kinds.append("wall" if r < 0.2 else "team" if r < 0.5 else "brick")
        if "brick" not in kinds:  # always at least one way through for everyone
            kinds[rng.randrange(len(kinds))] = "brick"
        for (x0, x1), kind in zip(segs, kinds):
            for yy in range(y, min(y + thick, start_top - 1)):
                if kind == "wall":
                    g[yy, x0:x1] = WALL
                elif kind == "team":
                    g[yy, x0:x1] = TEAM0 + rng.randrange(4)
                    hp[yy, x0:x1] = 1
                else:
                    g[yy, x0:x1] = BRICK
                    hp[yy, x0:x1] = rng.choice([1, 1, 1, 1, 2])
        # a few pillars between layers so paths wiggle
        if k < layers - 1 and rng.random() < 0.6:
            px = rng.randint(4, COLS - 6)
            g[y + thick + 1:y + thick + 1 + max(2, int(gap) - thick - 3), px:px + 2] = WALL
    g[start_top - 1, 1:-1] = np.where(g[start_top - 1, 1:-1] == 0, 0, g[start_top - 1, 1:-1])
    return g, hp, finish_row, start_top


# --------------------------------------------------------------------------- simulation
class Race:
    def __init__(self, g, hp, finish_row, start_top, seed, speed):
        self.g, self.hp = g.copy(), hp.copy()
        self.finish_row, self.speed = finish_row, speed
        self.rng = random.Random(seed)
        self.frame = 0
        self.events = []  # (frame, kind, row) for gen.build_audio
        self.changed = []
        self.winner = None
        self.balls = []
        cx = COLS / 2
        for t in range(4):
            x = cx + (t - 1.5) * 2.2
            ang = math.radians(self.rng.uniform(-150, -30))  # upward
            self.balls.append([x, ROWS - 3.0, math.cos(ang) * speed, math.sin(ang) * speed])
        self.best_y = [b[1] for b in self.balls]

    def solid_for(self, t, r, c):
        if r < 0 or c < 0 or r >= ROWS or c >= COLS:
            return True
        v = self.g[r, c]
        return v == WALL or v == BRICK or v >= TEAM0

    def hit(self, t, r, c):
        v = self.g[r, c]
        if v == BRICK or v == TEAM0 + t:
            self.hp[r, c] -= 1
            self.events.append((self.frame, "brick", r))
            if self.hp[r, c] <= 0:
                self.g[r, c] = EMPTY
            self.changed.append((r, c))

    def _fix(self, b):
        sp = math.hypot(b[2], b[3]) or 1
        ang = math.atan2(b[3], b[2]) + self.rng.uniform(-0.08, 0.08)
        # never let a ball fly almost flat (it would bounce side to side forever)
        s = math.sin(ang)
        if abs(s) < 0.3:
            s = math.copysign(0.3, s if s else -1)
            c = math.copysign(math.sqrt(1 - s * s), math.cos(ang))
            ang = math.atan2(s, c)
        b[2], b[3] = math.cos(ang) * self.speed, math.sin(ang) * self.speed

    def step(self):
        self.changed = []
        sub = max(1, int(math.ceil(self.speed / 0.3)))
        for _ in range(sub):
            for t, b in enumerate(self.balls):
                b[3] -= LIFT * self.speed / sub
                k = self.speed / (math.hypot(b[2], b[3]) or 1)
                b[2] *= k
                b[3] *= k
                for axis in (0, 1):
                    d = b[2 + axis] / sub
                    nx, ny = (b[0] + d, b[1]) if axis == 0 else (b[0], b[1] + d)
                    lead = math.copysign(R_BALL, d)
                    if axis == 0:
                        cells = [(int(ny + o), int(nx + lead)) for o in (-R_BALL * 0.7, 0, R_BALL * 0.7)]
                    else:
                        cells = [(int(ny + lead), int(nx + o)) for o in (-R_BALL * 0.7, 0, R_BALL * 0.7)]
                    hit = [rc for rc in set(cells) if self.solid_for(t, *rc)]
                    if hit:
                        for rc in hit:
                            self.hit(t, *rc)
                        b[2 + axis] = -b[2 + axis]
                        self._fix(b)
                    else:
                        b[0], b[1] = nx, ny
            # ball-ball bumps (equal mass, elastic)
            for i in range(4):
                for j in range(i + 1, 4):
                    a, c = self.balls[i], self.balls[j]
                    dx, dy = c[0] - a[0], c[1] - a[1]
                    dist = math.hypot(dx, dy)
                    if 0 < dist < 2 * R_BALL:
                        nx, ny = dx / dist, dy / dist
                        rel = (a[2] - c[2]) * nx + (a[3] - c[3]) * ny
                        if rel > 0:
                            a[2] -= rel * nx; a[3] -= rel * ny
                            c[2] += rel * nx; c[3] += rel * ny
                            self._fix(a); self._fix(c)
                            self.events.append((self.frame, "paddle", 0))
                        push = (2 * R_BALL - dist) / 2
                        a[0] -= nx * push; a[1] -= ny * push
                        c[0] += nx * push; c[1] += ny * push
        for t, b in enumerate(self.balls):
            self.best_y[t] = min(self.best_y[t], b[1])
            if self.winner is None and b[1] - R_BALL < self.finish_row:
                self.winner = t
        self.frame += 1

    def leader(self, prev=None, margin=1.5):
        """Highest ball; the current leader keeps the lead unless someone is clearly (margin cells) above it."""
        top = min(range(4), key=lambda t: self.best_y[t])  # furthest climbed so far
        if prev is not None and self.best_y[top] > self.best_y[prev] - margin:
            return prev
        return top


def run_race(g, hp, fr, st, seed, speed, cap):
    r = Race(g, hp, fr, st, seed, speed)
    leaders = []
    while r.winner is None and r.frame < cap:
        r.step()
        if r.frame % 15 == 0:
            leaders.append(r.leader(leaders[-1] if leaders else None))
    if r.winner is None:
        return None
    # time the runner-up would need: keep going a bit to measure the gap
    first_t, winner = r.frame, r.winner
    finished = {winner}
    second = None
    while r.frame < first_t + 8 * FPS:
        r.step()
        for t, b in enumerate(r.balls):
            if t not in finished and b[1] - R_BALL < fr:
                finished.add(t)
                second = r.frame
        if second:
            break
    gap = ((second or r.frame) - first_t) / FPS
    changes = sum(1 for a, b in zip(leaders, leaders[1:]) if a != b)
    return first_t, winner, gap, changes


def tune(seed, target, verbose=True):
    rng = random.Random(seed * 13)
    best = None
    for layers in rng.sample(LAYER_OPTIONS, len(LAYER_OPTIONS)):
        g, hp, fr, st = build_course(seed, layers)
        for speed in (0.8, 1.1, 1.4, 1.7, 2.0):
            probe = run_race(g, hp, fr, st, seed + 1, speed, int(target * FPS * 2.5))
            if probe is None or abs(probe[0] / FPS - target) > target * 0.45:
                continue
            for s in range(seed + 1, seed + 15):
                res = run_race(g, hp, fr, st, s, speed, int(target * FPS * 2.5))
                if res is None:
                    continue
                t, win, gap, ch = res
                if gap < 0.3:
                    continue
                score = abs(t / FPS - target) / target * 6 + min(gap, 8) / 2.5 - min(ch, 6) * 0.25
                if best is None or score < best[0]:
                    best = (score, layers, speed, s, t, win, gap, ch)
            if best and best[0] < 0.5:
                break
        if best and best[0] < 0.5:
            break
    if best is None:
        raise gen.TooLong("no finishing escape race found")
    _, layers, speed, s, t, win, gap, ch = best
    if verbose:
        print(f"  escape: {layers} layers, speed {speed:.2f} -> ball {win + 1} escapes at {t / FPS:.1f}s,"
              f" next one {gap:.1f}s later, {ch} lead change(s) (target {target:.0f}s)")
    return layers, speed, s, t, win, gap, ch


# --------------------------------------------------------------------------- rendering
class Painter:
    def __init__(self, race, theme, teams=TEAMS):
        self.r, self.th, self.teams = race, THEMES[theme], teams
        self.board = np.zeros((H, W, 3), np.uint8)
        self.board[:] = self.th["bg"]
        for rr in range(ROWS):
            for cc in range(COLS):
                self.paint(rr, cc)
        self.trail = []
        R = int(CELL * R_BALL)
        yy, xx = np.mgrid[-R - 1:R + 2, -R - 1:R + 2]
        d = np.sqrt(xx * xx + yy * yy)
        self.stamp = np.clip(R + 0.5 - d, 0, 1)[..., None]
        self.edge = np.clip(R + 0.5 - d, 0, 1)[..., None] - np.clip(R - 2.5 - d, 0, 1)[..., None]
        self.sr = R + 1

    def paint(self, r, c):
        v = self.r.g[r, c]
        y0, x0 = OY + r * CELL, OX + c * CELL
        blk = self.board[y0:y0 + CELL, x0:x0 + CELL]
        th = self.th
        if v == EMPTY:
            blk[:] = th["bg"]
        elif v == WALL:
            blk[:] = th["wall_edge"]
            blk[1:-1, 1:-1] = th["wall"]
        elif v == FINISH:
            blk[:] = (25, 25, 30) if (r + c) % 2 else (245, 245, 245)
        else:
            if v == BRICK:
                col = np.array(th["brick"] if self.r.hp[r, c] <= 1 else th["brick2"], np.float32)
            else:
                col = np.array(self.teams[v - TEAM0][1], np.float32)
            blk[:] = (col * 0.6).astype(np.uint8)
            blk[2:-2, 2:-2] = col.astype(np.uint8)
            blk[2:5, 2:-2] = np.minimum(col * 1.2, 255).astype(np.uint8)

    def _ball(self, f, x, y, a, col):
        cx, cy = int(OX + x * CELL), int(OY + y * CELL)
        R = self.sr
        y0, y1, x0, x1 = cy - R, cy + R + 1, cx - R, cx + R + 1
        if y0 < 0 or x0 < 0 or y1 > H or x1 > W:
            return
        reg = f[y0:y1, x0:x1].astype(np.float32)
        m = self.stamp * a
        reg = reg * (1 - m) + np.array(col, np.float32) * m
        if a >= 1:  # dark outline keeps balls readable on both themes
            e = self.edge * 0.55
            reg = reg * (1 - e) + np.array((20, 20, 26), np.float32) * e
        f[y0:y1, x0:x1] = reg.astype(np.uint8)

    def frame(self, overlay=None):
        for rc in self.r.changed:
            self.paint(*rc)
        f = self.board.copy()
        pos = [(b[0], b[1]) for b in self.r.balls]
        for k, old in enumerate(self.trail):
            for t, (x, y) in enumerate(old):
                self._ball(f, x, y, 0.12 + 0.08 * k, self.teams[t][1])
        for t, (x, y) in enumerate(pos):
            self._ball(f, x, y, 1.0, self.teams[t][1])
        self.trail = (self.trail + [pos])[-4:]
        if overlay is not None:
            img, a = overlay
            f = (f.astype(np.float32) * (1 - a) + img * a).astype(np.uint8)
        return f


def end_card(theme, winner, gap, teams=TEAMS):
    th = THEMES[theme]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bw, bh = int(W * 0.84), int(H * 0.17)
    x0, y0 = (W - bw) // 2, (H - bh) // 2
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=40, fill=th["card"])
    name, col = teams[winner]
    head = f"{name} ESCAPES!"
    size = int(W * 0.088)
    while gen.font(size).getlength(head) > bw * 0.9:
        size -= 2
    d.text((W / 2, y0 + bh * 0.14), head, font=gen.font(size), fill=col, anchor="mt",
           stroke_width=max(2, size // 22), stroke_fill=(20, 20, 26))
    sub = "by a hair!" if gap < 0.6 else f"by {gap:.1f} seconds"
    d.text((W / 2, y0 + bh * 0.66), sub, font=gen.font(int(W * 0.05)), fill=th["sub"], anchor="mt")
    arr = np.array(img).astype(np.float32)
    return arr[..., :3], arr[..., 3:] / 255.0


class _AudioLayout:  # what gen.build_audio needs to pitch brick sounds by height
    brick_top, brick_bot = 3, ROWS - 9


def make_escape(cfg, out_path=None, preview=None, verbose=True):
    """cfg: seed, target, [theme 'dark'|'light'|None=random], [reject_over]. Returns metadata."""
    rng = random.Random(cfg["seed"])
    theme = cfg.get("theme") or rng.choice(["dark", "light"])
    layers, speed, sim_seed, t_win, win, gap, ch = tune(cfg["seed"], cfg["target"], verbose)
    limit = cfg.get("reject_over")
    if limit and t_win / FPS > limit:
        raise gen.TooLong(f"predicted {t_win / FPS:.0f}s > {limit:.0f}s")
    g, hp, fr, st = build_course(cfg["seed"], layers)
    race = Race(g, hp, fr, st, sim_seed, speed)
    teams = rng.sample(TEAMS, 4)  # shuffle which color is which ball, so no color has a home advantage
    pnt = Painter(race, theme, teams)
    total_bricks = int(((g == BRICK) | (g >= TEAM0)).sum())

    if preview:
        want = sorted(int(t * FPS) for t in preview)
        os.makedirs(cfg.get("outdir", "out"), exist_ok=True)
        saved = []
        while want and race.winner is None:
            race.step()
            fr_ = pnt.frame()
            if race.frame >= want[0]:
                p = os.path.join(cfg.get("outdir", "out"), f"escape_{theme}_{race.frame // FPS:03d}s.jpg")
                Image.fromarray(fr_).save(p, quality=90)
                saved.append(p)
                want.pop(0)
        return saved

    tmp_v, tmp_a, tmp_o = (out_path[:-4] + x for x in (".v.tmp.mp4", ".a.tmp.wav", ".tmp.mp4"))
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", tmp_v], stdin=subprocess.PIPE)
    total = 0
    cap = int(cfg.get("max_len", 180) * FPS)
    while race.winner is None and race.frame < cap:
        race.step()
        enc.stdin.write(pnt.frame().tobytes())
        total += 1
    end_frame = race.frame
    winner = race.winner if race.winner is not None else win
    card = end_card(theme, winner, gap, teams)
    race.changed = []
    for i in range(int(2.5 * FPS)):
        enc.stdin.write(pnt.frame((card[0], card[1] * min(1.0, i / 8))).tobytes())
        total += 1
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg video encode failed")
    gen.build_audio(race.events, total, _AudioLayout, end_frame, True, tmp_a)
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp_v, "-i", tmp_a, "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", tmp_o])
    if r.returncode != 0:
        raise RuntimeError("ffmpeg mux failed")
    os.replace(tmp_o, out_path)
    os.remove(tmp_v)
    os.remove(tmp_a)
    name = teams[winner][0]
    meta = dict(file=out_path, mode="escape", title="Brick Escape", seed=cfg["seed"], pattern=f"escape-{layers}",
                obstacle="course", palette=f"escape-{theme}", theme=theme, duration=round(total / FPS, 2),
                bricks=total_bricks, outcome=f"{name.lower()} escapes", cleared_pct=0,
                clear_time=round(end_frame / FPS, 1), start_balls=4, bonus_every=0, peak_balls=4, balls_lost=0,
                teams=[t[0] for t in TEAMS], winner=name, margin_s=round(gap, 1), lead_changes=ch)
    if verbose:
        print(f"  wrote {out_path}  ({total / FPS:.1f}s, {theme}, {name} escapes, next {gap:.1f}s later,"
              f" {ch} lead change(s))")
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=float, default=40)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--theme", default=None, choices=["dark", "light"])
    ap.add_argument("--out", default="escape.mp4")
    ap.add_argument("--preview", default=None)
    ap.add_argument("--outdir", default="out")
    a = ap.parse_args()
    cfg = dict(seed=a.seed if a.seed is not None else random.randint(1, 10 ** 6), target=a.target,
               theme=a.theme, outdir=a.outdir)
    print(f"seed {cfg['seed']}")
    if a.preview:
        for p in make_escape(cfg, preview=[float(x) for x in a.preview.split(",")]):
            print(p)
    else:
        make_escape(cfg, a.out)


if __name__ == "__main__":
    main()
