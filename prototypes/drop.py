import math, random, sys, numpy as np
from PIL import Image, ImageDraw
from common import *
import brick_breaker_gen as gen
W, H, FPS, SUB = 1080, 1920, 30, 4
X0, X1 = 150, 930                       # inside the phone-crop safe area
TOP, PEG_TOP, BIN_TOP, FLOOR = 250, 380, 1390, 1700
BALLS, EVERY = 80, 0.18                 # balls dropped, seconds between drops
TEAMS = [("RED", (235, 70, 70)), ("YELLOW", (245, 200, 40)), ("BLUE", (60, 130, 245)), ("GREEN", (50, 185, 95))]
seed = int(sys.argv[1]) if len(sys.argv) > 1 else 3
HEADLESS = len(sys.argv) > 2 and sys.argv[2] == "probe"
rng = random.Random(seed)
# pegs: staggered rows of small bricks with 3 hit points
pegs, gap = [], 70
rows = int((BIN_TOP - 70 - PEG_TOP) / gap)
for r in range(rows):
    off = 0 if r % 2 == 0 else gap / 2
    x = X0 + 35 + off
    while x < X1 - 30:
        pegs.append(dict(x=x, y=PEG_TOP + r * gap, hp=6, row=r, alive=True))
        x += gap
grid = {}
for i, p in enumerate(pegs):
    grid.setdefault((int(p["x"] // 80), int(p["y"] // 80)), []).append(i)
NB = 4
bw = (X1 - X0) / NB
bins = [0] * NB
balls, shards, events = [], [], []
R, PR, G = 13, 14, 1500.0
dropped, frame, end_frame, leader, changes = 0, 0, None, None, 0
enc = None if HEADLESS else Encoder(OUTV := "out_drop.v.mp4")
bg = np.zeros((H, W, 3), np.uint8); bg[:] = (14, 14, 20)
f_big, f_mid, f_small = gen.font(96), gen.font(52), gen.font(40)
while True:
    t = frame / FPS
    if dropped < BALLS and t >= dropped * EVERY:
        balls.append([rng.uniform(X0 + 50, X1 - 50), TOP, rng.uniform(-40, 40), 0.0])
        dropped += 1
    dt = 1 / FPS / SUB
    for _ in range(SUB):
        keep = []
        for b in balls:
            b[3] += G * dt; b[0] += b[2] * dt; b[1] += b[3] * dt
            if abs(b[2]) + abs(b[3]) < 40 and b[1] < BIN_TOP:   # balanced on a peg: nudge it off
                b[2] += rng.choice((-1, 1)) * 120
            if b[0] < X0 + R: b[0], b[2] = X0 + R, abs(b[2]) * 0.6
            if b[0] > X1 - R: b[0], b[2] = X1 - R, -abs(b[2]) * 0.6
            gx, gy = int(b[0] // 80), int(b[1] // 80)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for i in grid.get((gx + dx, gy + dy), ()):
                        p = pegs[i]
                        if not p["alive"]: continue
                        ex, ey = b[0] - p["x"], b[1] - p["y"]
                        d = math.hypot(ex, ey)
                        if 0 < d < R + PR:
                            nx, ny = ex / d, ey / d
                            vn = b[2] * nx + b[3] * ny
                            if vn < 0:
                                b[2] -= 1.55 * vn * nx; b[3] -= 1.55 * vn * ny
                                b[2] += rng.uniform(-25, 25)
                                if -vn > 260:
                                    p["hp"] -= 1
                                    events.append((frame, "tick", p["row"]))
                                    if p["hp"] <= 0:
                                        p["alive"] = False
                                        events.append((frame, "break", p["row"]))
                                        col = gen.hsv(p["row"] / rows * 0.8, 0.7, 0.95)
                                        for _k in range(6):
                                            a = rng.uniform(0, 6.28)
                                            shards.append([p["x"], p["y"], math.cos(a) * 160, math.sin(a) * 160 - 120, 1.0, col])
                            b[0] = p["x"] + nx * (R + PR); b[1] = p["y"] + ny * (R + PR)
            # bin dividers
            for k in range(1, NB):
                wx = X0 + k * bw
                if b[1] > BIN_TOP and abs(b[0] - wx) < R + 4:
                    b[0] = wx + (R + 4) * (1 if b[0] > wx else -1); b[2] = -b[2] * 0.4
            if b[1] > FLOOR - 40 - bins[min(NB - 1, max(0, int((b[0] - X0) // bw)))] * 5:
                k = min(NB - 1, max(0, int((b[0] - X0) // bw)))
                bins[k] += 1
                events.append((frame, "land", k))
                lead = max(range(NB), key=lambda j: bins[j])
                if bins.count(bins[lead]) == 1 and lead != leader:
                    if leader is not None: changes += 1
                    leader = lead
            else:
                keep.append(b)
        balls = keep
    if dropped == BALLS and not balls and end_frame is None:
        end_frame = frame
    # ---- draw
    if HEADLESS:
        frame += 1
        if end_frame is not None or frame > FPS * 40: break
        continue
    img = Image.fromarray(bg.copy()); d = ImageDraw.Draw(img)
    for k in range(NB):  # bins
        x0 = X0 + k * bw; name, col = TEAMS[k]
        hgt = bins[k] * 5
        d.rectangle((x0 + 6, FLOOR - hgt, x0 + bw - 6, FLOOR), fill=tuple(int(v * 0.8) for v in col))
        d.rectangle((x0 + 6, BIN_TOP, x0 + bw - 6, FLOOR), outline=(60, 60, 72), width=3)
        d.text((x0 + bw / 2, FLOOR + 50), name, font=f_small, fill=col, anchor="mm")
        d.text((x0 + bw / 2, BIN_TOP - 40), str(bins[k]), font=f_mid, fill=(235, 235, 245), anchor="mm")
    for k in range(1, NB):
        wx = X0 + k * bw
        d.rectangle((wx - 4, BIN_TOP, wx + 4, FLOOR), fill=(120, 122, 132))
    d.rectangle((X0 - 10, TOP - 60, X0, FLOOR), fill=(120, 122, 132)); d.rectangle((X1, TOP - 60, X1 + 10, FLOOR), fill=(120, 122, 132))
    d.rectangle((X0 - 10, FLOOR, X1 + 10, FLOOR + 10), fill=(120, 122, 132))
    for p in pegs:
        if not p["alive"]: continue
        c = gen.hsv(p["row"] / rows * 0.8, 0.7, 0.95 * (0.5 + 0.083 * p["hp"]))
        dark = tuple(int(v * 0.55) for v in c)
        d.rectangle((p["x"] - PR, p["y"] - PR, p["x"] + PR, p["y"] + PR), fill=dark)
        d.rectangle((p["x"] - PR + 2, p["y"] - PR + 2, p["x"] + PR - 2, p["y"] + PR - 2), fill=c)
        if p["hp"] < 4:  # crack
            d.line((p["x"] - 6, p["y"] - 7, p["x"] + 2, p["y"] + 1, p["x"] - 1, p["y"] + 8), fill=(20, 20, 26), width=2)
    keep = []
    for s in shards:
        s[3] += 900 / FPS; s[0] += s[2] / FPS; s[1] += s[3] / FPS; s[4] -= 0.04
        if s[4] > 0:
            keep.append(s); c = tuple(int(v * s[4] + 14 * (1 - s[4])) for v in s[5])
            d.rectangle((s[0] - 5, s[1] - 5, s[0] + 5, s[1] + 5), fill=c)
    shards = keep
    for b in balls:
        d.ellipse((b[0] - R, b[1] - R, b[0] + R, b[1] + R), fill=(250, 250, 250))
    if end_frame is not None:
        a = min(1, (frame - end_frame) / 8)
        win = max(range(NB), key=lambda j: bins[j]); name, col = TEAMS[win]
        box = Image.new("RGBA", (W, H), (0, 0, 0, 0)); bd = ImageDraw.Draw(box)
        bd.rounded_rectangle((110, H * 0.4, W - 110, H * 0.57), radius=40, fill=(10, 10, 14, int(235 * a)))
        bd.text((W / 2, H * 0.43), f"{name} WINS!", font=f_big, fill=col + (int(255 * a),), anchor="mt",
                stroke_width=3, stroke_fill=(20, 20, 26, int(255 * a)))
        second = sorted(bins)[-2]
        bd.text((W / 2, H * 0.515), f"{bins[win]} balls to {second}", font=f_mid, fill=(225, 225, 235, int(255 * a)), anchor="mt")
        img = Image.alpha_composite(img.convert("RGBA"), box).convert("RGB")
        if frame - end_frame > 2.5 * FPS: break
    enc.write(np.array(img)); frame += 1
    if frame > FPS * 60: break
if HEADLESS:
    sb = sorted(bins)
    print(seed, bins, changes, round(frame / FPS, 1), sb[-1] - sb[-2]); sys.exit()
enc.close()
mix = np.zeros(int(frame / FPS * SR) + SR, np.float32)
pent = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21, 24, 26, 28]
nrng = np.random.default_rng(1); last_tick = -1
for fr, kind, k in events:
    i = int(fr / FPS * SR); tt = fr / FPS
    if kind == "tick":
        if tt - last_tick < 0.025: continue
        last_tick = tt
        add(mix, i, bell(880 * 2 ** (pent[(rows - 1 - k) % len(pent)] / 12), 0.12, 0.09, 30))
    elif kind == "break":
        n = int(0.18 * SR); add(mix, i, (nrng.standard_normal(n) * np.exp(-np.arange(n) / SR * 25) * 0.12).astype(np.float32))
    else:
        add(mix, i, bell(196 * 2 ** ([0, 4, 7, 12][k] / 12), 0.4, 0.25, 8))
if end_frame is not None:
    for j, n in enumerate((523, 659, 784, 1047)):
        add(mix, int((end_frame / FPS + j * 0.09) * SR), bell(n, 1.0, 0.3, 3))
write_wav("out_drop.wav", mix)
mux(OUTV, "out_drop.wav", "demo_drop.mp4")
print("seed", seed, "bins", bins, "lead changes", changes, "length", round(frame / FPS, 1))
