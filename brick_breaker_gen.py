#!/usr/bin/env python3
"""
Brick Breaker video generator  -  "oddly satisfying" ball-vs-bricks clips.

Renders vertical 1080x1920 MP4s (YouTube Shorts / X / TikTok ready) with sound.

Examples
  # one video, heart of bricks inside a vault with a single entrance, ~45 s long
  python3 brick_breaker_gen.py --pattern heart --obstacle vault --target 45 --out heart.mp4

  # 1 ball that splits every 60 bricks, custom hook text
  python3 brick_breaker_gen.py --balls 1 --split-every 60 --title "Can 1 ball clear this?" --out split.mp4

  # 10 random videos between 20 s and 2 min
  python3 brick_breaker_gen.py --batch 10 --min-len 20 --max-len 120 --outdir out/

  # just look at a few still frames (no encoding)
  python3 brick_breaker_gen.py --pattern rings --obstacle shelves --preview 1,10,30

Requires: python3, numpy, pillow, ffmpeg on PATH.
"""
import argparse
import math
import os
import random
import subprocess
import sys
import wave
from collections import deque

import numpy as np
from PIL import Image, ImageDraw, ImageFont

EMPTY, BRICK, WALL = 0, 1, 2
FPS = 30
FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

PATTERNS = ["solid", "heart", "circle", "diamond", "pyramid", "rings", "checker", "stripes", "text"]
OBSTACLES = ["none", "vault", "pillars", "shelves", "funnel", "maze"]
PALETTES = {  # (top color, bottom color) - bricks fade between them by row
    "red": ((235, 59, 59), (170, 28, 40)),
    "ocean": ((40, 190, 255), (45, 70, 210)),
    "sunset": ((255, 177, 66), (235, 64, 90)),
    "mint": ((60, 230, 170), (20, 150, 140)),
    "grape": ((190, 110, 255), (100, 45, 210)),
    "gold": ((255, 220, 90), (240, 140, 40)),
    "blue": ((80, 160, 255), (40, 70, 225)),
    "rainbow": None,
}


def font(size):
    for p in FONT_BOLD_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# --------------------------------------------------------------------------- layout
class Layout:
    def __init__(self, W=1080, H=1920, cell=20, margins=None):
        self.W, self.H, self.cell = W, H, cell
        self.hud = 0  # no on-screen HUD
        # Safe margins (plain background) for vertical video: phones are taller than 9:16 (~19.5:9), so
        # full-screen players crop ~9% off each side, and app buttons/captions overlap the top and bottom.
        vert = H > W
        mx = int(W * 0.115) if vert else 0
        mt = int(H * 0.04) if vert else 0
        mb = int(H * 0.06) if vert else 0
        if margins is not None:  # (left, right, top, bottom) in px, e.g. one half of a split-screen battle
            ml, mr, mt, mb = margins
        else:
            ml = mr = mx
        self.cols = (W - ml - mr) // cell
        self.rows = (H - mt - mb) // cell
        self.ox = ml + (W - ml - mr - self.cols * cell) // 2
        self.oy = mt + (H - mt - mb - self.rows * cell) // 2
        self.brick_top = 5
        self.brick_bot = int(self.rows * 0.64)
        self.paddle_row = self.rows - 6


# --------------------------------------------------------------------------- level
def pattern_mask(name, h, w, text="WOW"):
    yy, xx = np.mgrid[0:h, 0:w]
    s = min(h, w)
    u = (xx + 0.5 - w / 2) / (s / 2)
    v = (h / 2 - yy - 0.5) / (s / 2)
    if name == "solid":
        return np.ones((h, w), bool)
    if name == "circle":
        return u * u + v * v <= 0.97 ** 2
    if name == "heart":
        x, y = u * 1.18, v * 1.18 + 0.12
        return (x * x + y * y - 1) ** 3 - x * x * y ** 3 <= 0
    if name == "diamond":
        return np.abs(u) + np.abs(v) <= 1.0
    if name == "pyramid":
        return np.abs(xx + 0.5 - w / 2) <= (yy + 1) / h * (w / 2)
    if name == "rings":
        r = np.sqrt(u * u + v * v)
        return (r <= 0.98) & (np.floor(r * 7) % 2 == 0)
    if name == "checker":
        return ((yy // 5) + (xx // 5)) % 2 == 0
    if name == "stripes":
        return (yy // 3) % 2 == 0
    if name == "text":
        # Render each line big, crop tight, stack, then fit the block: full width, and letters may stretch up to
        # 2.2x taller than wide so short or long names fill the space and stay readable in bricks.
        f = font(400)
        tiles = []
        for ln in text.upper().split("/"):
            t = Image.new("L", (int(f.getlength(ln)) + 200, 600), 0)
            ImageDraw.Draw(t).text((100, 50), ln, fill=255, font=f)
            tiles.append(t.crop(t.getbbox()))
        gap = 90
        bw = max(t.width for t in tiles)
        bh = sum(t.height for t in tiles) + gap * (len(tiles) - 1)
        block = Image.new("L", (bw, bh), 0)
        y = 0
        for t in tiles:
            block.paste(t, ((bw - t.width) // 2, y))
            y += t.height + gap
        scale = 10
        W, H = w * scale * 0.96, h * scale * 0.9
        sx = min(W / bw, H / bh)
        sy = min(H / bh, sx * 2.2)
        block = block.resize((max(1, int(bw * sx)), max(1, int(bh * sy))), Image.LANCZOS)
        img = Image.new("L", (w * scale, h * scale), 0)
        img.paste(block, ((w * scale - block.width) // 2, (h * scale - block.height) // 2))
        small = img.resize((w, h), Image.BOX)
        return np.array(small) > 90
    raise ValueError(f"unknown pattern {name}")


def build_level(L, pattern, obstacle, rng, text="WOW", hp=1, vault_gap=2):
    R, C = L.rows, L.cols
    g = np.zeros((R, C), np.int8)
    g[0, :] = g[-1, :] = WALL
    g[:, 0] = g[:, -1] = WALL
    top, bot, left, right = L.brick_top, L.brick_bot, 2, C - 3
    mask = pattern_mask(pattern, bot - top + 1, right - left + 1, text)
    region = g[top:bot + 1, left:right + 1]
    region[mask] = BRICK
    wall_limit = L.paddle_row - 5  # keep paddle zone clear

    entry = None
    if obstacle == "vault":
        rs, cs = np.where(g == BRICK)
        r0, r1 = max(1, rs.min() - 1), min(wall_limit, rs.max() + 1)
        c0, c1 = max(1, cs.min() - 1), min(C - 2, cs.max() + 1)
        g[r0, c0:c1 + 1] = WALL
        g[r1, c0:c1 + 1] = WALL
        g[r0:r1 + 1, c0] = WALL
        g[r0:r1 + 1, c1] = WALL
        gx = rng.randint(c0 + 3, c1 - 3 - vault_gap)
        g[r1, gx:gx + vault_gap] = EMPTY
        entry = (r1, gx + vault_gap / 2)
    elif obstacle == "pillars":
        n = rng.randint(3, 5)
        for i in range(n):
            x = int(left + (i + 1) * (right - left) / (n + 1)) + rng.randint(-2, 2)
            y0 = rng.randint(top, bot - 10)
            g[y0:min(y0 + rng.randint(10, 22), wall_limit), x] = WALL
    elif obstacle == "shelves":
        step = rng.randint(9, 13)
        for y in range(top + step, bot + 2, step):
            g[y, 1:C - 1] = WALL
            for _ in range(2):
                gx = rng.randint(2, C - 6)
                g[y, gx:gx + 3] = EMPTY
    elif obstacle == "funnel":
        r0 = bot + 2
        i = 0
        while 1 + 2 * i < C // 2 - 5 and r0 + i < wall_limit:
            g[r0 + i, 1 + 2 * i:3 + 2 * i] = WALL
            g[r0 + i, C - 3 - 2 * i:C - 1 - 2 * i] = WALL
            i += 1
    elif obstacle == "maze":
        for _ in range(rng.randint(8, 12)):
            ln = rng.randint(5, 10)
            if rng.random() < 0.5:
                y, x = rng.randint(top, wall_limit - 1), rng.randint(2, C - 3 - ln)
                g[y, x:x + ln] = WALL
            else:
                y, x = rng.randint(top, wall_limit - ln), rng.randint(2, C - 3)
                g[y:y + ln, x] = WALL
    elif obstacle != "none":
        raise ValueError(f"unknown obstacle {obstacle}")

    # remove bricks the ball could never reach (sealed pockets)
    seen = np.zeros_like(g, bool)
    q = deque([(L.paddle_row - 1, C // 2)])
    seen[q[0]] = True
    while q:
        r, c = q.popleft()
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < R and 0 <= nc < C and not seen[nr, nc] and g[nr, nc] != WALL:
                seen[nr, nc] = True
                q.append((nr, nc))
    g[(g == BRICK) & ~seen] = EMPTY

    hpg = np.where(g == BRICK, hp, 0).astype(np.int16)
    return g, hpg, entry


# --------------------------------------------------------------------------- simulation
class Sim:
    def __init__(self, L, grid, hp, rng, speed=0.6, balls=3, split_every=0, max_balls=40, paddle_w=7,
                 lose=True, skill=0.85, collapse_at=None):
        self.L, self.g, self.hp, self.rng = L, grid.copy(), hp.copy(), rng
        self.lose, self.skill = lose, skill
        self.miss_p = max(0.0, 1.0 - skill) * 0.25  # chance the paddle fumbles a catch
        self.collapse_at = collapse_at  # fraction cleared after which the paddle starts choking
        self.lost = 0
        if lose:
            self.g[-1, 1:-1] = EMPTY  # open floor: missed balls drain out
        self.speed, self.split_every, self.max_balls, self.pw = speed, split_every, max_balls, paddle_w
        self.pr = L.paddle_row
        self.px = L.cols / 2
        self.total = int((self.g == BRICK).sum())
        self.destroyed = 0
        self.frame = 0
        self.balls = []
        self.pending = []
        self.events = []  # (frame, kind, row)
        self.changed = []  # cells to repaint this frame
        self.aim = 0.0
        self.aim_target = None
        self.aim_prob = 0.4
        self._targets, self._targets_at = None, -1
        for _ in range(balls):
            self._launch(self.px + rng.uniform(-2, 2), self.pr - 0.6)

    @property
    def done(self):
        return self.destroyed >= self.total

    @property
    def over(self):
        return self.lose and not self.balls and not self.pending and not self.done

    @property
    def finished(self):
        return self.done or self.over

    def _launch(self, x, y, ang=None):
        if ang is None:
            ang = math.radians(self.rng.uniform(20, 55) * self.rng.choice((-1, 1)))
        self.balls.append([x, y, math.sin(ang) * self.speed, -math.cos(ang) * self.speed])

    def _fix_angle(self, b, jitter=True):
        a = math.atan2(abs(b[2]), abs(b[3]))  # angle from the vertical axis, 0..pi/2
        if jitter:
            a += math.radians(self.rng.uniform(-2.5, 2.5))
        # keep away from pure horizontal / pure vertical loops
        a = min(max(a, math.radians(8)), math.radians(72))
        sgn_x = 1 if b[2] >= 0 else -1
        sgn_y = -1 if b[3] < 0 else 1
        b[2] = sgn_x * math.sin(a) * self.speed
        b[3] = sgn_y * math.cos(a) * self.speed

    def _hit(self, r, c, b):
        self.hp[r, c] -= 1
        self.events.append((self.frame, "brick", r))
        self.changed.append((r, c))
        if self.hp[r, c] <= 0:
            self.g[r, c] = EMPTY
            self.destroyed += 1
            choking = self.collapse_at is not None and self.destroyed >= self.collapse_at * self.total
            if (self.split_every and not choking and self.destroyed % self.split_every == 0
                    and len(self.balls) + len(self.pending) < self.max_balls):
                ang = math.atan2(b[2], -b[3]) + math.radians(self.rng.choice((-35, 35)))
                self.pending.append((b[0], b[1], ang))
                self.events.append((self.frame, "split", r))

    def _predict_x(self, b):
        t = (self.pr - b[1]) / b[3]
        x = b[0] + b[2] * t
        lo, hi = 1.0, self.L.cols - 1.0
        span = hi - lo
        x = (x - lo) % (2 * span)
        return lo + (x if x <= span else 2 * span - x)

    def step(self):
        self.changed = []
        L, g = self.L, self.g
        # paddle AI: chase the descending ball that arrives first, aiming off-center for varied angles
        best, bt = None, 1e9
        for b in self.balls:
            if b[3] > 0 and b[1] < self.pr:
                t = (self.pr - b[1]) / b[3]
                if t < bt:
                    best, bt = b, t
        if best is not None:
            if self.aim_target is not best:
                self.aim_target = best
                choking = self.collapse_at is not None and self.destroyed >= self.collapse_at * self.total
                late = self.destroyed > 0.75 * self.total
                p_miss = 0.5 if choking else self.miss_p
                if self.rng.random() < p_miss and (len(self.balls) > 1 or late or choking) and self.frame > 3 * FPS:
                    # fumble: paddle commits to the wrong spot and misses by a hair (near-miss drama)
                    self.aim = self.rng.choice((-1, 1)) * (self.pw / 2 + 1.3)
                else:
                    self.aim = self.rng.uniform(-0.8, 0.8) * self.pw / 2
            target = self._predict_x(best) - self.aim
            mv = self.speed * 1.9
            self.px += max(-mv, min(mv, target - self.px))
        self.px = min(max(self.px, 1 + self.pw / 2), L.cols - 1 - self.pw / 2)

        n = max(1, math.ceil(self.speed / 0.3))
        drained = []
        for b in self.balls:
            for _ in range(n):
                nx = b[0] + b[2] / n
                r, c = int(b[1]), int(nx)
                t = g[r, c]
                if t != EMPTY:
                    if t == BRICK:
                        self._hit(r, c, b)
                    b[2] = -b[2]
                    self._fix_angle(b)
                else:
                    b[0] = nx
                ny = b[1] + b[3] / n
                if self.lose and ny >= L.rows - 1:
                    drained.append(b)
                    self.lost += 1
                    self.events.append((self.frame, "lost", L.rows - 1))
                    if b is self.aim_target:
                        self.aim_target = None
                    break
                r, c = int(ny), int(b[0])
                t = g[r, c]
                if t != EMPTY:
                    if t == BRICK:
                        self._hit(r, c, b)
                    b[3] = -b[3]
                    self._fix_angle(b)
                elif b[3] > 0 and b[1] < self.pr <= ny and abs(b[0] - self.px) <= self.pw / 2 + 0.5:
                    off = max(-1.0, min(1.0, (b[0] - self.px) / (self.pw / 2)))
                    ang = math.radians(off * 58 + self.rng.uniform(-4, 4))
                    left = self.total - self.destroyed
                    if left and self.rng.random() < (1.0 if left < max(25, self.total * 0.04) else self.aim_prob):
                        # "skilled" paddle: send the ball toward a random remaining brick
                        if self._targets is None or self._targets_at != self.destroyed:
                            self._targets = np.argwhere(self.g == BRICK)
                            self._targets_at = self.destroyed
                        tr, tc = self._targets[self.rng.randrange(len(self._targets))]
                        ent = getattr(self.L, "entry", None)
                        if ent and b[1] > ent[0]:  # outside the vault: shoot for the entrance
                            tr, tc = ent[0] - 0.5, ent[1] - 0.5 + self.rng.uniform(-0.3, 0.3)
                        ang = math.atan2(tc + 0.5 - b[0], self.pr - (tr + 0.5))
                    b[2], b[3] = math.sin(ang) * self.speed, -math.cos(ang) * self.speed
                    self._fix_angle(b, jitter=False)
                    b[1] = self.pr - 0.01
                    self.events.append((self.frame, "paddle", self.pr))
                    if b is self.aim_target:
                        self.aim_target = None
                else:
                    b[1] = ny
        if drained:
            self.balls = [b for b in self.balls if all(b is not d for d in drained)]
        for x, y, ang in self.pending:
            self._launch(x, y, ang)
        self.pending = []
        self.frame += 1


def run_sim(L, grid, hp, seed, max_frames, **kw):
    """Headless run -> (frames, outcome, fraction cleared); outcome 'win', 'lose' or None (hit the cap)."""
    s = Sim(L, grid, hp, random.Random(seed), **kw)
    while not s.finished and s.frame < max_frames:
        s.step()
    return s.frame, ("win" if s.done else "lose" if s.over else None), s.destroyed / max(1, s.total)


def tune_speed(L, grid, hp, seed, target_s, kw, lo=0.6, hi=3.2, outcome="win"):
    """Search ball speeds for a deterministic run that ends near target_s with the wanted outcome
    ('win', 'lose' = game over after clearing 70%+, or 'any'). Returns (speed, frames, err, outcome)."""
    target = target_s * FPS
    cap = int(target * 2)
    best = (float("inf"), hi, None, None)

    def run(sp):
        nonlocal best
        f, res, pct = run_sim(L, grid, hp, seed, cap, speed=sp, **kw)
        ok = res is not None and (outcome == "any" or res == outcome) and (res != "lose" or pct >= 0.85)
        e = abs(f - target) if ok else float("inf")
        if e < best[0]:
            best = (e, sp, f, res)

    for sp in np.geomspace(lo, hi, 8):
        run(float(sp))
        if best[0] <= FPS:
            return best[1], best[2], best[0], best[3]
    if best[2] is not None:  # refine around the best speed found
        for sp in np.linspace(best[1] * 0.88, best[1] * 1.12, 6):
            run(float(sp))
            if best[0] <= FPS:
                break
    return best[1], best[2], best[0], best[3]


# --------------------------------------------------------------------------- rendering
def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def hsv(h, s=0.75, v=0.95):
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return (int(r * 255), int(g * 255), int(b * 255))


class Renderer:
    BG = np.array((14, 14, 20), np.uint8)
    BG_HUD = (10, 10, 14)
    WALL_IN, WALL_EDGE = np.array((120, 122, 132), np.uint8), np.array((78, 80, 90), np.uint8)
    PADDLE = (255, 140, 80)
    DRAIN = np.array((70, 16, 22), np.uint8)

    def __init__(self, L, sim, palette, title, hp_max):
        self.L, self.sim, self.title, self.hp_max = L, sim, title, max(1, hp_max)
        self.palette = palette
        self.ball_color = (255, 255, 255)
        self.board = np.zeros((L.H, L.W, 3), np.uint8)
        self.board[:] = self.BG
        for r in range(L.rows):
            for c in range(L.cols):
                self.paint(r, c)
        self.flashes = []
        self.lost_seen, self.drain_flash = 0, 0
        self.trail = deque(maxlen=4)
        self.hud_key = None
        self.hud_img = None
        self.f_title, self.f_small = font(int(L.W * 0.052)), font(int(L.W * 0.032))
        R = min(int(L.cell * 0.45), 13)
        yy, xx = np.mgrid[-R - 1:R + 2, -R - 1:R + 2]
        d = np.sqrt(xx * xx + yy * yy)
        self.stamp = np.clip(R + 0.5 - d, 0, 1)[..., None]
        self.stamp_r = R + 1

    def brick_color(self, r):
        t = (r - self.L.brick_top) / max(1, self.L.brick_bot - self.L.brick_top)
        t = min(max(t, 0), 1)
        if self.palette == "rainbow":
            return hsv(t * 0.85)
        a, b = PALETTES[self.palette]
        return lerp(a, b, t)

    def paint(self, r, c):
        L, cs = self.L, self.L.cell
        y0, x0 = L.oy + r * cs, L.ox + c * cs
        blk = self.board[y0:y0 + cs, x0:x0 + cs]
        t = self.sim.g[r, c]
        if t == EMPTY:
            blk[:] = self.DRAIN if (self.sim.lose and r == self.L.rows - 1) else self.BG
        elif t == WALL:
            blk[:] = self.WALL_EDGE
            blk[2:-2, 2:-2] = self.WALL_IN
        else:
            col = np.array(self.brick_color(r), float)
            hp = self.sim.hp[r, c]
            col *= 1 - 0.22 * (hp - 1) / self.hp_max
            blk[:] = (col * 0.55).astype(np.uint8)
            blk[2:-2, 2:-2] = col.astype(np.uint8)
            blk[2:4, 2:-2] = np.minimum(col * 1.25, 255).astype(np.uint8)

    def _blend_ball(self, f, x, y, alpha, color=(255, 255, 255)):
        L, R = self.L, self.stamp_r
        cx, cy = int(L.ox + x * L.cell), int(L.oy + y * L.cell)
        x0, y0, x1, y1 = cx - R, cy - R, cx + R + 1, cy + R + 1
        if x0 < 0 or y0 < 0 or x1 > L.W or y1 > L.H:
            return
        a = self.stamp * alpha
        reg = f[y0:y1, x0:x1].astype(np.float32)
        f[y0:y1, x0:x1] = (reg * (1 - a) + np.array(color, np.float32) * a).astype(np.uint8)

    def frame(self, overlay=None):
        s, L, cs = self.sim, self.L, self.L.cell
        for r, c in s.changed:
            self.paint(r, c)
            if s.g[r, c] == EMPTY:
                self.flashes.append([r, c, 0, self.brick_color(r)])
        f = self.board.copy()
        keep = []
        for fl in self.flashes:
            r, c, age, col = fl
            a = 1 - age / 7
            y0, x0 = L.oy + r * cs, L.ox + c * cs
            blk = f[y0:y0 + cs, x0:x0 + cs].astype(np.float32)
            glow = np.array(lerp((255, 255, 255), col, age / 7), np.float32)
            f[y0:y0 + cs, x0:x0 + cs] = (blk * (1 - a) + glow * a).astype(np.uint8)
            fl[2] += 1
            if fl[2] < 7:
                keep.append(fl)
        self.flashes = keep
        # drain flash when a ball is lost
        if s.lost > self.lost_seen:
            self.lost_seen, self.drain_flash = s.lost, 10
        if self.drain_flash:
            y0 = L.oy + (L.rows - 1) * cs
            a = self.drain_flash / 10
            reg = f[y0:y0 + cs, L.ox + cs:L.ox + (L.cols - 1) * cs].astype(np.float32)
            f[y0:y0 + cs, L.ox + cs:L.ox + (L.cols - 1) * cs] = (reg * (1 - a) + np.array((255, 50, 60)) * a).astype(np.uint8)
            self.drain_flash -= 1
        # paddle
        px0 = int(L.ox + (s.px - s.pw / 2) * cs)
        px1 = int(L.ox + (s.px + s.pw / 2) * cs)
        py0 = int(L.oy + s.pr * cs)
        f[py0:py0 + int(cs * 0.7), px0:px1] = self.PADDLE
        # trails then balls
        pos = [(b[0], b[1]) for b in s.balls]
        for i, old in enumerate(self.trail):
            a = 0.10 + 0.08 * i
            for x, y in old:
                self._blend_ball(f, x, y, a, self.ball_color)
        for x, y in pos:
            self._blend_ball(f, x, y, 1.0, self.ball_color)
        self.trail.append(pos)
        if overlay is not None:
            img, a = overlay
            f[:] = (f.astype(np.float32) * (1 - a) + img[..., :3] * a).astype(np.uint8)
        return f

    def end_card(self, secs, won=True):
        L = self.L
        img = Image.new("RGBA", (L.W, L.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        bw, bh = int(L.W * 0.8), int(L.H * 0.17)
        x0, y0 = (L.W - bw) // 2, (L.H - bh) // 2
        d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=40, fill=(10, 10, 14, 235))
        if won:
            head, sub, col = "CLEARED!", f"in {secs // 60}:{secs % 60:02d}", self.brick_color(L.brick_top)
        else:
            left = self.sim.total - self.sim.destroyed
            head = "GAME OVER"
            sub = f"{left} brick{'s' if left != 1 else ''} left  \u2022  {100 * self.sim.destroyed // self.sim.total}% cleared"
            col = (255, 80, 90)
        d.text((L.W / 2, y0 + bh * 0.16), head, font=font(int(L.W * (0.11 if won else 0.1))), fill=(255, 255, 255), anchor="mt")
        d.text((L.W / 2, y0 + bh * 0.66), sub, font=font(int(L.W * 0.05)), fill=col, anchor="mt")
        draw_card_extras(d, L.W, y0 + bh + int(L.W * 0.04), getattr(self, "card_extras", None))
        arr = np.array(img).astype(np.float32)
        return arr[..., :3], arr[..., 3:] / 255.0


# --------------------------------------------------------------------------- end-card extras
TEAM_RGB = {"RED": (255, 95, 95), "BLUE": (95, 175, 255), "GREEN": (80, 225, 150), "PURPLE": (195, 125, 255),
            "YELLOW": (250, 210, 60)}


def draw_card_extras(d, W, y, extras, light=False, winner=None):
    """Below the result box: season standings (races only) and a subscribe line.
    extras = {"season": n, "standings": {"RED": 3, ...} (wins BEFORE this video), "subscribe": "..."}"""
    if not extras:
        return
    fill = (250, 250, 248, 240) if light else (10, 10, 14, 235)
    muted = (110, 112, 124) if light else (140, 140, 155)
    if extras.get("standings") is not None:
        st = dict(extras["standings"])
        if winner:
            st[winner] = st.get(winner, 0) + 1
        items = sorted(st.items(), key=lambda kv: (-kv[1], kv[0]))[:4]
        bw, bh = int(W * 0.8), int(W * 0.2)
        x0 = (W - bw) // 2
        d.rounded_rectangle((x0, y, x0 + bw, y + bh), radius=30, fill=fill)
        d.text((W / 2, y + bh * 0.27), f"SEASON {extras.get('season', 1)} STANDINGS", font=font(int(W * 0.032)),
               fill=muted, anchor="mm")
        sep = "  \u2022  "
        size = int(W * 0.05)
        while True:
            f = font(size)
            parts = [(f"{n.title()} {k}", TEAM_RGB.get(n, (230, 230, 240))) for n, k in items]
            total = sum(d.textlength(t, font=f) for t, _ in parts) + d.textlength(sep, font=f) * (len(parts) - 1)
            if total <= bw * 0.92 or size < 20:
                break
            size -= 2
        x = W / 2 - total / 2
        for i, (txt, col) in enumerate(parts):
            d.text((x, y + bh * 0.66), txt, font=f, fill=col, anchor="lm",
                   stroke_width=2 if light else 0, stroke_fill=(30, 30, 36))
            x += d.textlength(txt, font=f)
            if i < len(parts) - 1:
                d.text((x, y + bh * 0.66), sep, font=f, fill=muted, anchor="lm")
                x += d.textlength(sep, font=f)
        y += bh + int(W * 0.035)
    if extras.get("subscribe"):
        f = font(int(W * 0.038))
        txt = extras["subscribe"]
        tw = d.textlength(txt, font=f)
        ph = int(W * 0.085)
        d.rounded_rectangle((W / 2 - tw / 2 - W * 0.04, y, W / 2 + tw / 2 + W * 0.04, y + ph), radius=ph // 2,
                            fill=(225, 35, 45, 245))
        d.text((W / 2, y + ph / 2), txt, font=f, fill=(255, 255, 255), anchor="mm")


# --------------------------------------------------------------------------- audio
def cold_open(sims, max_s=3.0, frac=0.03):
    """Run the first moments without recording, so frame 1 already shows bricks breaking (viewers decide in a
    second whether to swipe). Steps all sims together until one has broken `frac` of its bricks (min 3) or
    `max_s` seconds pass. Returns the number of skipped frames; earlier events are dropped."""
    start = sims[0].frame
    while sims[0].frame - start < max_s * FPS and not any(s.finished for s in sims):
        if any(s.destroyed >= max(3, s.total * frac) for s in sims):
            break
        for s in sims:
            s.step()
    for s in sims:
        s.events = []
        s.changed = []
    return sims[0].frame - start


def shift_events(events, offset):
    return [(f - offset, k, r) for f, k, r in events if f >= offset]


def build_audio(events, total_frames, L, end_frame, won, path, sr=44100, soft=False):
    """soft=True (relax videos): quieter, rounder, longer notes, gentle paddle, plus a slow ambient pad."""
    n = int(total_frames / FPS * sr) + sr
    mix = np.zeros(n, np.float32)
    semis = [0, 2, 4, 7, 9]
    notes = [330 * 2 ** ((o * 12 + s) / 12) for o in range(3) for s in semis]  # pentatonic, 3 octaves

    def tone(freq, dur, amp, decay, harm=0.3):
        t = np.arange(int(dur * sr)) / sr
        w = np.sin(2 * np.pi * freq * t) + harm * np.sin(4 * np.pi * freq * t)
        return (w * np.exp(-t * decay) * amp).astype(np.float32)

    cache = {}
    last = -1.0
    for fr, kind, row in events:
        t0 = fr / FPS
        if kind == "brick":
            if t0 - last < (0.07 if soft else 0.022):
                continue
            last = t0
            frac = 1 - (row - L.brick_top) / max(1, L.brick_bot - L.brick_top)
            idx = int(min(max(frac, 0), 0.999) * len(notes))
            key = ("b", idx)
            if key not in cache:
                cache[key] = (tone(notes[idx] / 2, 0.6, 0.09, 6, harm=0.08) if soft
                              else tone(notes[idx], 0.12, 0.22, 38))
            w = cache[key]
        elif kind == "paddle":
            if "p" not in cache:
                cache["p"] = tone(110, 0.25, 0.07, 14, harm=0.1) if soft else tone(150, 0.09, 0.28, 45, harm=0.6)
            w = cache["p"]
        elif kind == "lost":
            if "l" not in cache:
                t = np.arange(int(0.35 * sr)) / sr
                fr = 320 * np.exp(-t * 3.2)  # falling "bwoop"
                cache["l"] = (np.sin(2 * np.pi * np.cumsum(fr) / sr) * np.exp(-t * 6) * 0.35).astype(np.float32)
            w = cache["l"]
        elif kind == "split":
            if "s" not in cache:
                cache["s"] = np.concatenate([tone(f, 0.06, 0.18, 30) for f in (660, 880, 1320)])
            w = cache["s"]
        else:
            continue
        i = int(t0 * sr)
        mix[i:i + len(w)] += w[: max(0, n - i)]
    if soft:  # slow-breathing pad: A minor-ish chord, fades with a 9 s LFO
        t = np.arange(n) / sr
        lfo = 0.55 + 0.45 * np.sin(2 * np.pi * t / 9.0)
        pad = sum(np.sin(2 * np.pi * f * t + k) for k, f in enumerate((110.0, 164.8, 220.0, 261.6)))
        mix += (pad * lfo * 0.018).astype(np.float32)
    if end_frame is not None and not soft:
        i = int(end_frame / FPS * sr)
        notes_end = (523, 659, 784, 1047) if won else (392, 311, 262, 196)
        gap = 0.09 if won else 0.22
        for k, f in enumerate(notes_end):
            w = tone(f, 0.7, 0.3, 4)
            j = i + int(k * gap * sr)
            mix[j:j + len(w)] += w[: max(0, n - j)]
    out = np.tanh(mix * 1.1) * 0.85
    pcm = (out * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


# --------------------------------------------------------------------------- driver
class TooLong(Exception):
    """Raised by make_video() when cfg['reject_over'] is set and the tuned run would be longer than that."""


MAX_PX_PER_SEC = 1500  # fastest ball speed the tuner will use (keeps it watchable)
CELL_SIZES = [20, 24, 30, 36, 45, 54]  # px; all divide 1080. Smaller = more bricks.


def setup_level(cfg, cell):
    L = Layout(*cfg["size"], cell=cell)
    grid, hp, entry = build_level(L, cfg["pattern"], cfg["obstacle"], random.Random(cfg["seed"]),
                                  cfg["text"], cfg["hp"], cfg["vault_gap"])
    L.entry = entry
    return L, grid, hp


def make_video(cfg, out_path=None, preview=None, verbose=True):
    kw = dict(balls=cfg["balls"], split_every=cfg["split_every"], max_balls=cfg["max_balls"],
              paddle_w=cfg["paddle_w"], lose=cfg["lose"], skill=cfg["skill"])
    sim_seed = cfg["seed"] + 1
    speed = cfg["speed"]
    cells = [cfg["cell"]] if cfg["cell"] else [c for c in CELL_SIZES if c <= (cfg.get("max_cell") or 999)]
    outcome = cfg["outcome"] if cfg["lose"] else "win"
    if cfg["skill"] is None:
        kw["skill"] = cfg["skill"] = 0.85
    if outcome == "lose":  # paddle "chokes" near the end: fumbles a lot, no more bonus balls
        kw["collapse_at"] = random.Random(cfg["seed"] * 3).uniform(0.88, 0.97)

    if cfg["target"] and speed is None:
        # Finest bricks first; then fewest balls; then try a few sim seeds until a run lands on target.
        mb = cfg["max_balls"]
        if cfg["balls"]:
            ball_opts = [(cfg["balls"], cfg["split_every"], mb)]
        elif cfg["lose"] and not cfg["split_every"] and outcome == "lose":
            # (start balls, bonus ball every N bricks, ball cap): a capped swarm can still drain out
            ball_opts = [(1, 15, 8), (1, 15, 12), (3, 20, 10), (1, 25, 10), (6, 0, mb), (16, 0, mb)]
        elif cfg["lose"] and not cfg["split_every"]:
            # race between dropped balls and bonus balls is the fun part
            ball_opts = [(1, 15, mb), (1, 25, mb), (3, 30, mb), (6, 0, mb), (16, 0, mb)]
        else:
            ball_opts = [(n, cfg["split_every"], mb) for n in (3, 6, 10, 16)]
        seeds = [cfg["seed"] + k for k in range(1, 4)]
        best, tol = None, max(1.5 * FPS, 0.08 * cfg["target"] * FPS)
        for cell in cells:
            L, grid, hp = setup_level(cfg, cell)
            kw["paddle_w"] = cfg["paddle_w"] or max(3, round(150 / cell))
            hi = cfg.get("max_px_per_sec", MAX_PX_PER_SEC) / (cell * FPS)
            for nb in ball_opts:
                kw["balls"], kw["split_every"], kw["max_balls"] = nb
                for ss in seeds:
                    sp, f, err, res = tune_speed(L, grid, hp, ss, cfg["target"], kw, lo=hi * 0.3, hi=hi, outcome=outcome)
                    if f is not None and (best is None or err < best[0]):
                        best = (err, cell, nb, sp, f, ss, res)
                    if best and best[0] <= tol:
                        break
                if best and best[0] <= tol:
                    break
            if best and best[0] <= tol:
                break
        if best is None:  # nothing worked: biggest bricks, most balls, top speed
            best = (0, cells[-1], ball_opts[-1], MAX_PX_PER_SEC / (cells[-1] * FPS), None, seeds[0], None)
        _, cell, (kw["balls"], kw["split_every"], kw["max_balls"]), speed, f, sim_seed, res = best
        cfg["balls"], cfg["split_every"] = kw["balls"], kw["split_every"]
        L, grid, hp = setup_level(cfg, cell)
        kw["paddle_w"] = cfg["paddle_w"] or max(3, round(150 / cell))
        if verbose:
            got = f"ends ({res}) at {f / FPS:.1f}s" if f else "may not finish"
            sp_txt = f", +1 ball every {kw['split_every']} bricks" if kw["split_every"] else ""
            print(f"  bricks {cell}px, {kw['balls']} ball(s){sp_txt}, speed {speed:.2f} -> {got} (target {cfg['target']:.0f}s)")
        # Let callers skip designs the tuner can't fit, before spending time rendering them.
        limit = cfg.get("reject_over")
        if limit and (not f or f / FPS > limit):
            raise TooLong(f"predicted {'no finish' if not f else f'{f / FPS:.0f}s'} > {limit:.0f}s")
    else:
        kw["balls"] = kw["balls"] or 3
        L, grid, hp = setup_level(cfg, cells[0])
        kw["paddle_w"] = cfg["paddle_w"] or max(3, round(150 / cells[0]))
    speed = speed or 0.9

    sim = Sim(L, grid, hp, random.Random(sim_seed), speed=speed, **kw)
    pre = cold_open([sim]) if cfg.get("cold_open", True) else 0
    title = cfg["title"] or auto_title(cfg, sim.total)
    if verbose:
        print(f"  title: {title}")
    ren = Renderer(L, sim, cfg["palette"], title, cfg["hp"])
    ren.card_extras = cfg.get("card_extras")
    max_frames = int(cfg["max_len"] * FPS)
    hold = int((2.5 if cfg.get("end_card", True) else 1.5) * FPS)

    if preview:
        want = sorted(int(t * FPS) for t in preview)
        os.makedirs(cfg["outdir"], exist_ok=True)
        saved = []
        while want and sim.frame < max_frames and not sim.finished:
            sim.step()
            fr = ren.frame()
            if sim.frame >= want[0]:
                p = os.path.join(cfg["outdir"], f"preview_{sim.frame // FPS:03d}s.jpg")
                Image.fromarray(fr).save(p, quality=90)
                saved.append(p)
                want.pop(0)
        if sim.finished:
            p = os.path.join(cfg["outdir"], "preview_end.jpg")
            Image.fromarray(ren.frame(ren.end_card(sim.frame // FPS, sim.done))).save(p, quality=90)
            saved.append(p)
        return saved

    tmp_v = out_path[:-4] + ".video.tmp.mp4"
    tmp_a = out_path[:-4] + ".audio.tmp.wav"
    tmp_o = out_path[:-4] + ".tmp.mp4"
    W, H = cfg["size"]
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", tmp_v], stdin=subprocess.PIPE)
    total = 0
    while not sim.finished and sim.frame - pre < max_frames:
        sim.step()
        enc.stdin.write(ren.frame().tobytes())
        total += 1
    end_frame = sim.frame - pre if sim.finished else None
    card = (ren.end_card((sim.frame - pre) // FPS, sim.done) if sim.finished and cfg.get("end_card", True)
            else None)
    sim.changed = []
    for i in range(hold):
        ov = None
        if card is not None:
            a = min(1.0, i / 8)
            ov = (card[0], card[1] * a)
        enc.stdin.write(ren.frame(ov).tobytes())
        total += 1
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg video encode failed")
    build_audio(shift_events(sim.events, pre), total, L, end_frame, sim.done, tmp_a, soft=cfg.get("soft_audio", False))
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp_v, "-i", tmp_a, "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", tmp_o])
    if r.returncode != 0:
        raise RuntimeError("ffmpeg mux failed")
    os.replace(tmp_o, out_path)
    os.remove(tmp_v)
    os.remove(tmp_a)
    meta = dict(file=out_path, title=title, seed=cfg["seed"], pattern=cfg["pattern"], obstacle=cfg["obstacle"],
                palette=cfg["palette"], duration=round(total / FPS, 2), bricks=sim.total,
                outcome="win" if sim.done else "lose" if sim.over else "timeout",
                cleared_pct=100 * sim.destroyed // max(1, sim.total),
                clear_time=round(end_frame / FPS, 1) if end_frame else None,
                start_balls=kw["balls"], bonus_every=kw["split_every"], peak_balls=max(len(sim.balls), kw["balls"]),
                balls_lost=sim.lost)
    if verbose:
        status = (f"cleared at {end_frame / FPS:.1f}s" if sim.done else
                  f"GAME OVER at {end_frame / FPS:.1f}s, {100 * sim.destroyed // sim.total}% cleared" if sim.over
                  else "hit max length")
        print(f"  wrote {out_path}  ({total / FPS:.1f}s, {sim.total} bricks, {len(sim.balls)} balls, {status})")
    return meta


HOOKS = {
    "vault": ["Only one way in...", "Can it break into the vault?", "One tiny gap. Can it get in?"],
    "split": ["Every {n} bricks = 1 more ball", "It splits every {n} bricks...", "Watch it multiply"],
    "single": ["Can 1 ball clear the {shape}?", "1 ball vs {count} bricks"],
    "lose": ["Will it make it?", "Don't drop the last ball...", "Every miss costs a ball", "Can it clear before it runs out?"],
    "generic": ["Wait for the last brick", "Guess how long this takes", "Don't look away before 100%",
                "{count} bricks. How long?", "So satisfying to watch"],
}


def auto_title(cfg, total_bricks):
    shape = cfg["pattern"] if cfg["pattern"] not in ("solid", "text", "stripes", "checker") else "wall"
    pool = list(HOOKS["generic"])
    if cfg["obstacle"] == "vault":
        pool += HOOKS["vault"] * 2
    if cfg["split_every"]:
        pool += HOOKS["split"] * 2
    if cfg["balls"] == 1:
        pool += HOOKS["single"] * 2
    if cfg["lose"]:
        pool += HOOKS["lose"] * 3
    t = random.Random(cfg["seed"] * 7).choice(pool)
    return t.format(n=cfg["split_every"], shape=shape, count=f"{total_bricks:,}")


SIZES = {"vertical": (1080, 1920), "square": (1080, 1080), "landscape": (1920, 1080)}


def default_cfg(**over):
    """Every setting make_video() needs, with the CLI defaults. Override with keyword args."""
    cfg = dict(pattern="solid", text="WOW", obstacle="none", palette="red", balls=None, split_every=0,
               max_balls=40, hp=1, paddle_w=None, vault_gap=2, cell=None, max_cell=None, lose=True, outcome="win",
               skill=None, target=None, speed=None, max_len=180, title=None, size=SIZES["vertical"],
               outdir="out", seed=None)
    cfg.update(over)
    return cfg


def random_cfg(master, base, min_len=20, max_len=90, lose_share=0.3):
    """Randomize shape, obstacle, colors, ball setup, length and ending on top of `base`."""
    cfg = dict(base)
    cfg["seed"] = master.randint(1, 10 ** 6)
    cfg["pattern"] = master.choice([p for p in PATTERNS if p != "text"])
    cfg["obstacle"] = master.choice(OBSTACLES)
    cfg["palette"] = master.choice(list(PALETTES))
    style = master.choice(["multi", "multi", "split"])
    cfg["balls"] = None if style == "multi" else 1
    cfg["split_every"] = master.choice([15, 25, 40]) if style == "split" else 0
    cfg["hp"] = master.choice([1, 1, 1, 2])
    if cfg["lose"]:
        cfg["outcome"] = "lose" if master.random() < lose_share else "win"
    cfg["target"] = round(master.uniform(min_len, max_len))
    cfg["speed"] = None
    cfg["max_len"] = max(cfg.get("max_len", 180), cfg["target"] * 1.5)
    return cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pattern", default="solid", choices=PATTERNS)
    ap.add_argument("--text", default="WOW", help="word(s) for --pattern text; use / for a line break")
    ap.add_argument("--obstacle", default="none", choices=OBSTACLES)
    ap.add_argument("--palette", default="red", choices=list(PALETTES))
    ap.add_argument("--balls", type=int, default=None, help="starting balls (default: auto with --target, else 3)")
    ap.add_argument("--split-every", type=int, default=0, help="add a ball every N bricks destroyed (0 = off)")
    ap.add_argument("--max-balls", type=int, default=40)
    ap.add_argument("--hp", type=int, default=1, help="hits needed per brick")
    ap.add_argument("--paddle-w", type=int, default=None, help="paddle width in cells (default ~150px)")
    ap.add_argument("--cell", type=int, default=None, help="brick size in px (default: auto, finest that fits --target)")
    ap.add_argument("--vault-gap", type=int, default=2, help="entrance width for --obstacle vault")
    ap.add_argument("--no-lose", action="store_true", help="balls can't be lost (closed floor)")
    ap.add_argument("--outcome", default="win", choices=["win", "lose", "any"],
                    help="ending to aim for when balls can be lost (lose = GAME OVER after 70%%+ cleared)")
    ap.add_argument("--skill", type=float, default=None,
                    help="paddle skill 0-1 (1 = never fumbles; default 0.85, or 0.7 when aiming for a loss)")
    ap.add_argument("--target", type=float, default=None, help="target length in seconds (auto-tunes speed)")
    ap.add_argument("--speed", type=float, default=None, help="ball speed in cells/frame (overrides --target)")
    ap.add_argument("--max-len", type=float, default=180, help="hard cap on length in seconds")
    ap.add_argument("--title", default=None, help="hook text used for captions/YouTube title (auto if omitted; not drawn on the video)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--format", default="vertical", choices=["vertical", "square", "landscape"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--preview", default=None, help="comma list of seconds to save as JPGs instead of a video")
    ap.add_argument("--batch", type=int, default=0, help="make N random videos")
    ap.add_argument("--min-len", type=float, default=20)
    ap.add_argument("--max-len-batch", dest="max_len_b", type=float, default=90, help="longest target in --batch mode")
    a = ap.parse_args()

    base = default_cfg(pattern=a.pattern, text=a.text, obstacle=a.obstacle, palette=a.palette, balls=a.balls,
                       split_every=a.split_every, max_balls=a.max_balls, hp=a.hp, paddle_w=a.paddle_w,
                       vault_gap=a.vault_gap, cell=a.cell, lose=not a.no_lose, outcome=a.outcome, skill=a.skill,
                       target=a.target, speed=a.speed, max_len=a.max_len, title=a.title,
                       size=SIZES[a.format], outdir=a.outdir)
    os.makedirs(a.outdir, exist_ok=True)

    if a.batch:
        master = random.Random(a.seed if a.seed is not None else None)
        for i in range(a.batch):
            cfg = random_cfg(master, base, a.min_len, a.max_len_b)
            name = f"{i + 1:02d}_{cfg['pattern']}_{cfg['obstacle']}_{int(cfg['target'])}s.mp4"
            print(f"[{i + 1}/{a.batch}] {name}")
            make_video(cfg, os.path.join(a.outdir, name))
        return

    cfg = dict(base)
    cfg["seed"] = a.seed if a.seed is not None else random.randint(1, 10 ** 6)
    if a.preview:
        for p in make_video(cfg, preview=[float(x) for x in a.preview.split(",")]):
            print(p)
        return
    out = a.out or os.path.join(a.outdir, f"{cfg['pattern']}_{cfg['obstacle']}_{cfg['seed']}.mp4")
    print(f"seed {cfg['seed']}")
    make_video(cfg, out)


if __name__ == "__main__":
    main()
