#!/usr/bin/env python3
"""
Color battles: split-screen race. Two teams (e.g. RED vs BLUE) get identical walls of bricks, the same
ball setup and the same speed; only the luck of the bounces differs. First side to clear wins.

Because the sim is deterministic, we run a dozen candidate bounce-seeds headlessly first and pick the
pair with the closest finish (and the most lead changes), so viewers stay to the end. The winner's
color is picked at random.

  python3 battle.py --target 45 --out battle.mp4          # one battle
  python3 battle.py --preview 5,20 --seed 3               # stills only
"""
import argparse
import os
import random
import subprocess

import numpy as np
from PIL import Image, ImageDraw

import brick_breaker_gen as gen
from brick_breaker_gen import FPS

W, H = 1080, 1920
HALF = W // 2
# (left, right, top, bottom) margins per half: outer sides keep the phone-crop safe margin, the middle stays
# narrow, and the top is taller to fit the team names.
M_OUT, M_MID, M_TOP, M_BOT = int(W * 0.115), 12, int(H * 0.085), int(H * 0.06)

TEAMS = {  # name -> (brick palette, ball/label color)
    "RED": ("red", (255, 95, 95)),
    "BLUE": ("blue", (95, 175, 255)),
    "GREEN": ("mint", (80, 235, 170)),
    "PURPLE": ("grape", (195, 125, 255)),
    "GOLD": ("gold", (255, 210, 80)),
}
PATTERNS = ["solid", "pyramid", "diamond", "heart", "circle", "checker", "stripes", "rings"]
OBSTACLES = ["none", "none", "none", "pillars", "shelves"]
CELLS = [16, 20, 24]


def configure(w, h):
    """Switch canvas size, e.g. configure(1920, 1080) for widescreen compilations. Default is 1080x1920."""
    global W, H, HALF, M_OUT, M_MID, M_TOP, M_BOT
    W, H, HALF = w, h, w // 2
    if h > w:  # vertical: phone-crop safe sides, room for team names on top
        M_OUT, M_MID, M_TOP, M_BOT = int(w * 0.115), 12, int(h * 0.085), int(h * 0.06)
    else:      # widescreen: no crop to worry about
        M_OUT, M_MID, M_TOP, M_BOT = int(w * 0.03), 14, int(h * 0.13), int(h * 0.04)


def pick_teams(rng):
    if rng.random() < 0.5:
        return "RED", "BLUE"
    a, b = rng.sample(list(TEAMS), 2)
    return a, b


def layout(side, cell):
    m = (M_OUT, M_MID, M_TOP, M_BOT) if side == 0 else (M_MID, M_OUT, M_TOP, M_BOT)
    L = gen.Layout(HALF, H, cell=cell, margins=m)
    # a half is tall and narrow: brick block up to ~2.3x as tall as it is wide
    L.brick_bot = min(int(L.rows * 0.55), L.brick_top + int((L.cols - 4) * 2.3))
    return L


def level(cfg, cell):
    L = layout(0, cell)
    grid, hp, _ = gen.build_level(L, cfg["pattern"], cfg["obstacle"], random.Random(cfg["seed"]), "", cfg["hp"])
    return L, grid, hp


def race_curve(L, grid, hp, seed, kw, cap):
    """Headless run -> (finish frame or None, progress fraction sampled every 15 frames)."""
    s = gen.Sim(L, grid, hp, random.Random(seed), **kw)
    curve = []
    while not s.done and s.frame < cap:
        s.step()
        if s.frame % 15 == 0:
            curve.append(s.destroyed / max(1, s.total))
    return (s.frame if s.done else None), np.array(curve)


def lead_changes(a, b):
    n = min(len(a), len(b))
    d = np.sign(a[:n] - b[:n])
    d = d[d != 0]
    return int((d[1:] != d[:-1]).sum()) if len(d) > 1 else 0


def tune(cfg, verbose=True):
    """Pick brick size, balls, speed and two bounce-seeds for a close race that ends near cfg['target']."""
    rng = random.Random(cfg["seed"] * 11)
    target = cfg["target"]
    styles = [(1, 10), (1, 15), (1, 25), (3, 0), (5, 0)]  # (start balls, +1 ball every N bricks)
    rng.shuffle(styles)
    best = None
    for cell in CELLS:
        L, grid, hp = level(cfg, cell)
        if int((grid == gen.BRICK).sum()) < 60:
            continue
        hi = gen.MAX_PX_PER_SEC / (cell * FPS)
        for balls, every in styles:
            kw = dict(balls=balls, split_every=every, max_balls=40, paddle_w=max(3, round(150 / cell)),
                      lose=False, skill=0.85)
            sp, f, err, _ = gen.tune_speed(L, grid, hp, cfg["seed"] + 1, target, kw, lo=hi * 0.3, hi=hi, outcome="win")
            if f is None:
                continue
            kw["speed"] = sp
            runs = [(s,) + race_curve(L, grid, hp, s, kw, int(target * FPS * 2)) for s in
                    range(cfg["seed"] + 1, cfg["seed"] + 13)]
            runs = [r for r in runs if r[1] is not None]
            for i in range(len(runs)):
                for j in range(i + 1, len(runs)):
                    (sa, fa, ca), (sb, fb, cb) = runs[i], runs[j]
                    gap = abs(fa - fb) / FPS
                    if gap < 0.4:
                        continue  # too close to read as a win
                    win_t = min(fa, fb) / FPS
                    score = (abs(win_t - target) / target * 6 + min(gap, 8) / 2.5
                             - min(lead_changes(ca, cb), 4) * 0.35)
                    if best is None or score < best[0]:
                        best = (score, cell, dict(kw), sa, sb, fa, fb, lead_changes(ca, cb))
        if best and best[0] < 1.0:
            break
    if best is None:
        raise gen.TooLong("no finishing race found")
    _, cell, kw, sa, sb, fa, fb, lc = best
    if verbose:
        print(f"  battle: bricks {cell}px, {kw['balls']} ball(s)"
              + (f", +1 every {kw['split_every']}" if kw["split_every"] else "")
              + f", speed {kw['speed']:.2f} -> finishes {min(fa, fb) / FPS:.1f}s vs {max(fa, fb) / FPS:.1f}s,"
              f" {lc} lead change(s) (target {target:.0f}s)")
    limit = cfg.get("reject_over")
    if limit and min(fa, fb) / FPS > limit:
        raise gen.TooLong(f"predicted {min(fa, fb) / FPS:.0f}s > {limit:.0f}s")
    # faster seed -> winner; winner side/color chosen at random
    fast, slow = (sa, sb) if fa < fb else (sb, sa)
    return cell, kw, fast, slow, abs(fa - fb) / FPS, lc


def draw_label(ren, text, color):
    L = ren.L
    img = Image.fromarray(ren.board)
    d = ImageDraw.Draw(img)
    f = gen.font(min(int(L.W * 0.13), int(L.oy * 0.72)))  # fit the top margin (widescreen has less room)
    cx = L.ox + L.cols * L.cell / 2
    d.text((cx, L.oy / 2), text, font=f, fill=color, anchor="mm")
    ren.board = np.array(img)


def end_card(winner, color, loser, left_bricks, gap):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bw, bh = int(W * 0.8), int(H * 0.17)
    x0, y0 = (W - bw) // 2, (H - bh) // 2
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=40, fill=(10, 10, 14, 235))
    d.text((W / 2, y0 + bh * 0.14), f"{winner} WINS!", font=gen.font(int(W * 0.1)), fill=color, anchor="mt")
    sub = f"{loser} had {left_bricks} brick{'s' if left_bricks != 1 else ''} left" if left_bricks > 3 \
        else f"by {gap:.1f} seconds"
    d.text((W / 2, y0 + bh * 0.66), sub, font=gen.font(int(W * 0.05)), fill=(225, 225, 235), anchor="mt")
    arr = np.array(img).astype(np.float32)
    return arr[..., :3], arr[..., 3:] / 255.0


def make_battle(cfg, out_path=None, preview=None, verbose=True):
    """cfg keys: seed, pattern, obstacle, hp, target, [reject_over], [teams]. Returns metadata like make_video()."""
    rng = random.Random(cfg["seed"])
    cfg.setdefault("pattern", rng.choice(PATTERNS))
    cfg.setdefault("obstacle", rng.choice(OBSTACLES))
    cfg.setdefault("hp", 1)
    teams = cfg.get("teams") or pick_teams(rng)
    cell, kw, fast, slow, gap, lc = tune(cfg, verbose)
    win_side = rng.randrange(2)
    seeds = [fast, slow] if win_side == 0 else [slow, fast]

    sims, rens = [], []
    for side in (0, 1):
        L = layout(side, cell)
        grid, hp, _ = gen.build_level(L, cfg["pattern"], cfg["obstacle"], random.Random(cfg["seed"]), "", cfg["hp"])
        sim = gen.Sim(L, grid, hp, random.Random(seeds[side]), **kw)
        palette, color = TEAMS[teams[side]]
        ren = gen.Renderer(L, sim, palette, "", cfg["hp"])
        ren.ball_color = tuple(min(255, int(c * 0.6 + 255 * 0.4)) for c in color)
        ren.PADDLE = color
        draw_label(ren, teams[side], color)
        sims.append(sim)
        rens.append(ren)

    def frame(overlay=None):
        f = np.hstack([rens[0].frame(), rens[1].frame()])
        if overlay is not None:
            img, a = overlay
            f = (f.astype(np.float32) * (1 - a) + img * a).astype(np.uint8)
        return f

    max_frames = int(cfg.get("max_len", 180) * FPS)
    done = lambda: any(s.done for s in sims)  # noqa: E731

    if preview:
        want = sorted(int(t * FPS) for t in preview)
        os.makedirs(cfg.get("outdir", "out"), exist_ok=True)
        saved = []
        while want and not done() and sims[0].frame < max_frames:
            for s in sims:
                s.step()
            fr = frame()
            if sims[0].frame >= want[0]:
                p = os.path.join(cfg.get("outdir", "out"), f"battle_{sims[0].frame // FPS:03d}s.jpg")
                Image.fromarray(fr).save(p, quality=90)
                saved.append(p)
                want.pop(0)
        return saved

    tmp_v, tmp_l, tmp_r, tmp_o = (out_path[:-4] + x for x in (".v.tmp.mp4", ".l.tmp.wav", ".r.tmp.wav", ".tmp.mp4"))
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", tmp_v], stdin=subprocess.PIPE)
    total = 0
    while not done() and sims[0].frame < max_frames:
        for s in sims:
            s.step()
        enc.stdin.write(frame().tobytes())
        total += 1
    end_frame = sims[0].frame
    winner = next((i for i, s in enumerate(sims) if s.done), win_side)
    loser = 1 - winner
    left = sims[loser].total - sims[loser].destroyed
    card = end_card(teams[winner], TEAMS[teams[winner]][1], teams[loser], left, gap)
    for s in sims:
        s.changed = []
    hold = int(2.5 * FPS)
    for i in range(hold):
        enc.stdin.write(frame((card[0], card[1] * min(1.0, i / 8))).tobytes())
        total += 1
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg video encode failed")
    # each team's sounds lean toward its side of the stereo field; only the winner plays the victory jingle
    gen.build_audio(sims[0].events, total, sims[0].L, end_frame if winner == 0 else None, True, tmp_l)
    gen.build_audio(sims[1].events, total, sims[1].L, end_frame if winner == 1 else None, True, tmp_r)
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", tmp_v, "-i", tmp_l, "-i", tmp_r, "-filter_complex",
         "[1:a][2:a]amerge=inputs=2,pan=stereo|c0=0.62*c0+0.18*c1|c1=0.18*c0+0.62*c1[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
         "-movflags", "+faststart", tmp_o])
    if r.returncode != 0:
        raise RuntimeError("ffmpeg mux failed")
    os.replace(tmp_o, out_path)
    for p in (tmp_v, tmp_l, tmp_r):
        os.remove(p)
    meta = dict(file=out_path, mode="battle", title=f"{teams[0]} vs {teams[1]}", seed=cfg["seed"],
                pattern=cfg["pattern"], obstacle=cfg["obstacle"], palette=f"{teams[0]}-vs-{teams[1]}".lower(),
                duration=round(total / FPS, 2), bricks=sims[0].total, outcome=f"{teams[winner].lower()} wins",
                cleared_pct=100, clear_time=round(end_frame / FPS, 1), start_balls=kw["balls"],
                bonus_every=kw["split_every"], peak_balls=max(len(s.balls) for s in sims), balls_lost=0,
                teams=list(teams), winner=teams[winner], margin_s=round(gap, 1), lead_changes=lc,
                loser_bricks_left=left)
    if verbose:
        print(f"  wrote {out_path}  ({total / FPS:.1f}s, {sims[0].total} bricks each, {teams[winner]} wins"
              f" by {gap:.1f}s, {lc} lead change(s))")
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=float, default=45)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--pattern", default=None, choices=PATTERNS)
    ap.add_argument("--obstacle", default=None, choices=sorted(set(OBSTACLES)))
    ap.add_argument("--teams", default=None, help="e.g. RED,BLUE")
    ap.add_argument("--out", default="battle.mp4")
    ap.add_argument("--preview", default=None, help="comma list of seconds to save as stills")
    ap.add_argument("--outdir", default="out")
    a = ap.parse_args()
    cfg = dict(seed=a.seed if a.seed is not None else random.randint(1, 10 ** 6), target=a.target, outdir=a.outdir)
    if a.pattern:
        cfg["pattern"] = a.pattern
    if a.obstacle:
        cfg["obstacle"] = a.obstacle
    if a.teams:
        cfg["teams"] = tuple(t.strip().upper() for t in a.teams.split(","))
    print(f"seed {cfg['seed']}")
    if a.preview:
        for p in make_battle(cfg, preview=[float(x) for x in a.preview.split(",")]):
            print(p)
    else:
        make_battle(cfg, a.out)


if __name__ == "__main__":
    main()
