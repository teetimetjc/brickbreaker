#!/usr/bin/env python3
"""
BRICK PICKS (sports): ONE ball drops through a board of peg-bricks into one of two team bins - "the bricks decide".
Pegs crack and shatter as the ball hits them. Seeds are simulated headlessly and the one with the tensest finish is
rendered: the ball wobbles near the middle late in the drop before falling to a side. `winner` can force a side
(e.g. for a result video); otherwise the physics picks. Team names as text + colors only, never logos.

  python3 picks.py --teams CHIEFS:e31837,BILLS:00338d --banner "THANKSGIVING · WHO DO THE BRICKS PICK?" --out pick.mp4
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
X0, X1 = 150, 930
TOP, PEG_TOP, BIN_TOP, FLOOR = 330, 470, 1400, 1640
R, PR, GAP = 17, 15, 80
G = 520.0            # low gravity = a slow, tense drop
INTRO = 1.4          # seconds the ball wobbles at the top before it drops
MID = (X0 + X1) / 2


def lift(rgb, lo=200):
    """Dark team colors (navy) brightened so they read on the black background."""
    r, g, b = rgb
    m = max(r, g, b)
    if m >= lo:
        return rgb
    k = lo / max(1, m)
    return tuple(min(255, int(v * k + 40)) for v in rgb)


class Run:
    def __init__(self, seed, hp=(1, 1, 2), pw=PR, ph=PR, balls=1, g=G, bounce=1.5, round_pegs=False, spacing=None, row_gap=GAP):
        self.rng = random.Random(seed)
        self.g, self.bounce, self.round = g, bounce, round_pegs
        self.pw, self.ph, self.balls_total = pw, ph, balls
        self.score, self.landed = [0, 0], []
        self.rows = int((BIN_TOP - 60 - PEG_TOP) / row_gap)
        self.pegs = []
        for r in range(self.rows):
            sp = spacing or max(GAP, 2 * self.pw + 2 * R + 14)   # room for the ball between bricks
            off = 0 if r % 2 == 0 else sp / 2
            x = X0 + 40 + off
            while x < X1 - 35:
                h0 = self.rng.choice(hp)
                self.pegs.append(dict(x=x, y=PEG_TOP + r * row_gap, hp=h0, hp0=h0, row=r, alive=True))
                x += sp
        self.ball = [MID + self.rng.uniform(-6, 6), TOP, self.rng.uniform(-30, 30), 0.0]
        self.frame, self.events, self.shards, self.side, self.end = 0, [], [], None, None
        self.next_drop = INTRO * FPS
        self.close = 1e9     # how near the middle the ball came in the bottom third (tension score)

    def step(self):
        rng, b = self.rng, self.ball
        self.frame += 1
        if self.frame < self.next_drop or self.side is not None or self.ball is None:
            return
        dt = 1 / FPS / SUB
        for _ in range(SUB):
            b[3] += self.g * dt
            b[2] *= 0.999
            b[0] += b[2] * dt
            b[1] += b[3] * dt
            if b[0] < X0 + R:
                b[0], b[2] = X0 + R, abs(b[2]) * 0.6
            if b[0] > X1 - R:
                b[0], b[2] = X1 - R, -abs(b[2]) * 0.6
            if abs(b[2]) + abs(b[3]) < 30 and b[1] < BIN_TOP:
                b[2] += rng.choice((-1, 1)) * 90
            for p in self.pegs:
                if not p["alive"] or abs(p["y"] - b[1]) > R + self.ph + 2 or abs(p["x"] - b[0]) > R + self.pw + 2:
                    continue
                # closest point on the brick rectangle -> circle/rect collision (works for square and wide bricks)
                if self.round:  # round contact (like a real peg): every hit deflects, nothing to slide along
                    dd = math.hypot(b[0] - p["x"], b[1] - p["y"]) or 1
                    k = min(1.0, self.pw / dd)
                    cx, cy = p["x"] + (b[0] - p["x"]) * k, p["y"] + (b[1] - p["y"]) * k
                else:
                    cx = min(max(b[0], p["x"] - self.pw), p["x"] + self.pw)
                    cy = min(max(b[1], p["y"] - self.ph), p["y"] + self.ph)
                ex, ey = b[0] - cx, b[1] - cy
                d = math.hypot(ex, ey)
                if 0 < d < R:
                    nx, ny = ex / d, ey / d
                    vn = b[2] * nx + b[3] * ny
                    if vn < 0:
                        b[2] -= self.bounce * vn * nx
                        b[3] -= self.bounce * vn * ny
                        b[2] += rng.uniform(-22, 22)
                        p["hp"] -= 1
                        if self.frame - p.get("hit", -99) > 4:   # one chime/flash per real hit, not per touch
                            self.events.append((self.frame, "tick", p["row"]))
                        p["hit"] = self.frame
                        if p["hp"] <= 0:
                            p["alive"] = False
                            self.events.append((self.frame, "break", p["row"]))
                            for _k in range(7):
                                a = rng.uniform(0, 6.28)
                                self.shards.append([p["x"], p["y"], math.cos(a) * 170, math.sin(a) * 170 - 130, 1.0,
                                                    p["x"] < MID])
                    b[0], b[1] = cx + nx * R, cy + ny * R
            if b[1] > PEG_TOP + (BIN_TOP - PEG_TOP) * 0.62:
                self.close = min(self.close, abs(b[0] - MID))
            if b[1] > BIN_TOP and abs(b[0] - MID) < R + 6:   # divider between the bins
                b[0] = MID + (R + 6) * (1 if b[0] > MID else -1)
                b[2] = -b[2] * 0.4
            if b[1] > FLOOR - 40:
                side = 0 if b[0] < MID else 1
                self.score[side] += 1
                self.landed.append((side, b[0]))
                self.events.append((self.frame, "land", side))
                need = self.balls_total // 2 + 1
                if self.score[side] >= need:
                    self.side, self.end = side, self.frame
                else:  # best of N: next ball after a short pause
                    self.ball = [MID + self.rng.uniform(-6, 6), TOP, self.rng.uniform(-30, 30), 0.0]
                    self.next_drop = self.frame + FPS * 0.9
                    self.close = 1e9
                return


def choose(seed, winner=None, verbose=True, style=None):
    """Seed whose drop lasts 5-11 s (per ball) and comes closest to the middle late on. winner: 0/1 or None."""
    style = style or {}
    best = None
    n = style.get("balls", 1)
    lo, hi, aim = (5, 11, 8) if n == 1 else (12, 26, 18)
    if min(style.get("hp", (1,))) > 50 and n == 1:   # solid bricks: the ball hits every row, so it takes longer
        lo, hi, aim = 7, 13, 10
    for s in range(seed, seed + 60):
        r = Run(s, **style)
        while r.side is None and r.frame < FPS * 25:
            r.step()
        if r.side is None or (winner is not None and r.side != winner):
            continue
        t = r.end / FPS - INTRO
        if not lo <= t <= hi:
            continue
        score = r.close + abs(t - aim) * 8 - (40 if n > 1 and min(r.score) == n // 2 else 0)  # best of 3: prefer 2-1
        if best is None or score < best[0]:
            best = (score, s, r.end, r.side, r.close)
    if best is None:
        raise gen.TooLong("no suitable drop found")
    if verbose:
        print(f"  pick: seed {best[1]}, lands {['left', 'right'][best[3]]} at {best[2] / FPS:.1f}s, "
              f"passed {best[4]:.0f}px from the middle")
    return best[1]


def football_sprite(scale=1.0):
    """A brown football with white laces and stripes, as an RGBA sprite (drawn once, rotated per frame)."""
    w, h = int(64 * scale), int(40 * scale)
    img = Image.new("RGBA", (w + 8, h + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 4 + w, 4 + h), fill=(120, 62, 30, 255), outline=(70, 34, 14, 255), width=3)
    cx, cy = 4 + w / 2, 4 + h / 2
    for sx in (-w * 0.3, w * 0.3):     # white end stripes
        d.line((cx + sx, cy - h * 0.38, cx + sx, cy + h * 0.38), fill=(240, 240, 240, 255), width=max(2, int(3 * scale)))
    d.line((cx - w * 0.16, cy, cx + w * 0.16, cy), fill=(245, 245, 245, 255), width=max(2, int(3 * scale)))
    for k in range(-2, 3):             # laces
        x = cx + k * w * 0.065
        d.line((x, cy - h * 0.11, x, cy + h * 0.11), fill=(245, 245, 245, 255), width=max(2, int(2 * scale)))
    return img


def field_background():
    """Turf: mowed stripes with yard lines, for the 'field' theme."""
    bg = Image.new("RGB", (W, H), (14, 14, 20))
    d = ImageDraw.Draw(bg)
    top, bot = TOP - 40, FLOOR
    n = 10
    for i in range(n):
        y0 = top + (bot - top) * i / n
        y1 = top + (bot - top) * (i + 1) / n
        d.rectangle((X0, y0, X1, y1), fill=(34, 102, 44) if i % 2 else (40, 116, 52))
        d.line((X0, y0, X1, y0), fill=(220, 235, 220), width=2)
    return np.array(bg)


def end_card(name, col, extras):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bw, bh = int(W * 0.8), int(W * 0.3)
    x0, y0 = (W - bw) // 2, int(H * 0.34)
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=40, fill=(10, 10, 14, 235))
    extras = dict(extras or {})
    head = extras.pop("headline", "BRICKS PICK {winner}").format(winner=name)
    fs = int(W * 0.095)
    while gen.font(fs).getlength(head) > bw * 0.9 and fs > 20:
        fs -= 2
    d.text((W / 2, y0 + bh * 0.16), head, font=gen.font(fs), fill=col, anchor="mt", stroke_width=3,
           stroke_fill=(20, 20, 26))
    sub = extras.pop("subline", "Who you got?").format(winner=name)
    fs2 = int(W * 0.05)
    while gen.font(fs2).getlength(sub) > bw * 0.9 and fs2 > 16:
        fs2 -= 2
    d.text((W / 2, y0 + bh * 0.64), sub, font=gen.font(fs2), fill=(225, 225, 235), anchor="mt")
    gen.draw_card_extras(d, W, y0 + bh + int(W * 0.04), extras, winner=name)
    arr = np.array(img).astype(np.float32)
    return arr[..., :3], arr[..., 3:] / 255.0


def make_pick(cfg, out_path, verbose=True):
    """cfg: teams [(NAME, (r,g,b)), (NAME, (r,g,b))], seed, [winner 0|1|NAME], [banner], [card_extras]."""
    teams = [(n.upper(), lift(tuple(c))) for n, c in cfg["teams"]]
    win = cfg.get("winner")
    if isinstance(win, str):
        win = [t[0] for t in teams].index(win.upper())
    style = cfg.get("style", {})
    seed = choose(cfg["seed"], win, verbose, style)
    run = Run(seed, **style)
    tmp_v, tmp_a = out_path[:-4] + ".v.tmp.mp4", out_path[:-4] + ".a.tmp.wav"
    enc = Encoder(tmp_v, W, H)
    bg = np.zeros((H, W, 3), np.uint8)
    bg[:] = (14, 14, 20)
    if cfg.get("theme") == "field":
        bg = field_background()
    ball_img = football_sprite() if cfg.get("ball") == "football" else None
    spin = 0.0
    f_team, f_vs, f_ban, f_bin = gen.font(78), gen.font(44), gen.font(36), gen.font(64)
    (na, ca), (nb, cb) = teams
    wall = (120, 122, 132)
    trail, card, after = [], None, 0
    while True:
        run.step()
        img = Image.fromarray(bg.copy())
        d = ImageDraw.Draw(img)
        # matchup header
        wa, wv, wb = f_team.getlength(na), f_vs.getlength("  vs  "), f_team.getlength(nb)
        x = W / 2 - (wa + wv + wb) / 2
        d.text((x, 150), na, font=f_team, fill=ca, anchor="lm")
        d.text((x + wa, 150), "  vs  ", font=f_vs, fill=(200, 200, 210), anchor="lm")
        d.text((x + wa + wv, 150), nb, font=f_team, fill=cb, anchor="lm")
        if cfg.get("banner"):
            d.text((W / 2, 235), cfg["banner"], font=f_ban, fill=(255, 210, 80), anchor="mm")
        # bins
        for k, (name, col) in enumerate(teams):
            bx0, bx1 = (X0, MID) if k == 0 else (MID, X1)
            lit = run.side == k
            fill = tuple(int(v * (0.55 if lit else 0.18)) for v in col)
            d.rectangle((bx0 + 6, BIN_TOP, bx1 - 6, FLOOR), fill=fill, outline=col, width=4)
            d.text(((bx0 + bx1) / 2, (BIN_TOP + FLOOR) / 2 + (0 if run.balls_total > 1 else 20)), name, font=f_bin,
                   fill=(255, 255, 255) if lit else col, anchor="mm")
            if run.balls_total > 1:
                d.text(((bx0 + bx1) / 2, (BIN_TOP + FLOOR) / 2 + 70), str(run.score[k]), font=f_vs,
                       fill=(235, 235, 245), anchor="mm")
        for k2, (sd, lx) in enumerate(run.landed):
            if run.side is None or k2 < len(run.landed) - 1:
                if ball_img is None:
                    d.ellipse((lx - R, FLOOR - 2 * R - 4, lx + R, FLOOR - 4), fill=(210, 210, 220))
                else:
                    img.paste(ball_img, (int(lx - ball_img.width / 2), int(FLOOR - ball_img.height - 4)), ball_img)
        d.rectangle((MID - 5, BIN_TOP - 10, MID + 5, FLOOR), fill=wall)
        d.rectangle((X0 - 10, TOP - 40, X0, FLOOR), fill=wall)
        d.rectangle((X1, TOP - 40, X1 + 10, FLOOR), fill=wall)
        d.rectangle((X0 - 10, FLOOR, X1 + 10, FLOOR + 10), fill=wall)
        # pegs: tinted toward the team whose side they are on
        for p in run.pegs:
            if not p["alive"]:
                continue
            col = ca if p["x"] < MID else cb
            c = tuple(int(v * 0.55 + 255 * 0.25) for v in col) if p["hp0"] > 1 else tuple(int(v * 0.85) for v in col)
            pw, ph = run.pw, run.ph
            d.rectangle((p["x"] - pw, p["y"] - ph, p["x"] + pw, p["y"] + ph), fill=tuple(int(v * 0.5) for v in c))
            d.rectangle((p["x"] - pw + 2, p["y"] - ph + 2, p["x"] + pw - 2, p["y"] + ph - 2), fill=c)
            if run.frame - p.get("hit", -99) < 5:  # flash when hit (unbreakable bricks stay put)
                d.rectangle((p["x"] - pw + 2, p["y"] - ph + 2, p["x"] + pw - 2, p["y"] + ph - 2), fill=(255, 255, 255))
            if p["hp"] < p["hp0"] < 50:  # cracked (breakable bricks only)
                d.line((p["x"] - 6, p["y"] - ph + 3, p["x"] + 2, p["y"], p["x"] - 2, p["y"] + ph - 3), fill=(20, 20, 26),
                       width=3)
        keep = []
        for s in run.shards:
            s[3] += 900 / FPS
            s[0] += s[2] / FPS
            s[1] += s[3] / FPS
            s[4] -= 0.035
            if s[4] > 0:
                keep.append(s)
                col = ca if s[5] else cb
                c = tuple(int(v * s[4] + 14 * (1 - s[4])) for v in col)
                d.rectangle((s[0] - 5, s[1] - 5, s[0] + 5, s[1] + 5), fill=c)
        run.shards = keep
        b = run.ball
        b = b if b is not None else [MID, TOP, 0, 0]
        bx = b[0] + (math.sin(run.frame * 0.9) * 5 if run.frame < run.next_drop else 0)  # nervous wobble before the drop
        trail = (trail + [(bx, b[1])])[-6:]
        for k, (tx, ty) in enumerate(trail[:-1] if ball_img is None else []):
            rr = R * (0.5 + 0.08 * k)
            cc = int(14 + 200 * (0.12 + 0.1 * k))
            d.ellipse((tx - rr, ty - rr, tx + rr, ty + rr), fill=(cc, cc, cc))
        if ball_img is None:
            d.ellipse((bx - R, b[1] - R, bx + R, b[1] + R), fill=(255, 255, 255))
        else:  # tumbling football: spin follows its sideways speed
            spin += (b[2] if run.frame >= run.next_drop else 0) / FPS * 1.6 + (6 if run.frame >= run.next_drop else 0)
            spr = ball_img.rotate(spin % 360, resample=Image.BICUBIC, expand=True)
            img.paste(spr, (int(bx - spr.width / 2), int(b[1] - spr.height / 2)), spr)
        f = np.array(img)
        if run.end is not None and run.frame > run.end + FPS * 0.6:
            if card is None:
                card = end_card(teams[run.side][0], teams[run.side][1], cfg.get("card_extras"))
            a = min(1.0, after / 8)
            f = (f.astype(np.float32) * (1 - card[1] * a) + card[0] * card[1] * a).astype(np.uint8)
            after += 1
            if after > 2.6 * FPS:
                enc.write(f)
                break
        enc.write(f)
    enc.close()
    mix = np.zeros(int(enc.n / FPS * SR) + SR, np.float32)
    pent = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21, 24]
    for fr, kind, k in run.events:
        i = int(fr / FPS * SR)
        if kind == "tick":
            add(mix, i, bell(523 * 2 ** (pent[k % len(pent)] / 12), 0.22, 0.2, 14))
        elif kind == "break":
            add(mix, i, noise_burst(0.2, 0.14, 22, fr))
        else:
            for j, st in enumerate((0, 4, 7, 12)):
                add(mix, i + int(j * 0.06 * SR), bell(262 * 2 ** (st / 12), 0.7, 0.22, 5))
    win_chime(mix, run.end / FPS + 0.6)
    write_wav(tmp_a, mix)
    mux(tmp_v, tmp_a, out_path)
    os.remove(tmp_v)
    os.remove(tmp_a)
    name = teams[run.side][0]
    if verbose:
        print(f"  wrote {out_path}  ({enc.n / FPS:.1f}s, bricks pick {name})")
    return dict(file=out_path, mode="pick", winner=name, teams=[t[0] for t in teams], duration=round(enc.n / FPS, 2),
                seed=seed)


def parse_teams(s):
    out = []
    for part in s.split(","):
        name, _, hx = part.partition(":")
        hx = hx.strip().lstrip("#") or "ffffff"
        out.append((name.strip(), tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", required=True, help="NAME:hex,NAME:hex  e.g. CHIEFS:e31837,BILLS:00338d")
    ap.add_argument("--winner", default=None, help="force a side (team name); default: the physics picks")
    ap.add_argument("--banner", default="")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default="pick.mp4")
    a = ap.parse_args()
    make_pick(dict(teams=parse_teams(a.teams), seed=a.seed if a.seed is not None else random.randint(1, 10 ** 6),
                   winner=a.winner, banner=a.banner,
                   card_extras={"subscribe": "FOLLOW FOR BRICK PICKS", "subline": "Who you got?"}), a.out)


if __name__ == "__main__":
    main()
