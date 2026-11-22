import math, random, numpy as np
from PIL import Image, ImageDraw
from common import *
import brick_breaker_gen as gen
W, H, FPS = 1080, 1920, 30
CX, CY = W / 2, H * 0.47
rng = random.Random(13)
NR = 7
rings = []
for i in range(NR):
    R = 95 + i * 50
    n = int(2 * math.pi * R / 26)
    rings.append(dict(R=R, n=n, rot=rng.uniform(0, 6.28), spd=(0.9 + 0.12 * i) * (1 if i % 2 else -1),
                      gap=math.radians(58), alive=True, color=gen.hsv(i / NR * 0.85, 0.75, 0.95)))
ball = dict(x=CX, y=CY, vx=rng.uniform(-260, 260), vy=-380, r=15)
GRAV, SUB = 950.0, 6
shards, events, trail = [], [], []

def ang_in_gap(a, ring):
    d = (a - ring["rot"]) % (2 * math.pi)
    return d < ring["gap"]

frames_total, end_frame = 0, None
enc = Encoder(S := "out/rings.v.mp4")
bg = np.zeros((H, W, 3), np.uint8); bg[:] = (14, 14, 20)
fnt = gen.font(92); fnt2 = gen.font(44)
for frame in range(FPS * 40):
    dt = 1 / FPS / SUB
    for _ in range(SUB):
        ball["vy"] += GRAV * dt
        ball["x"] += ball["vx"] * dt; ball["y"] += ball["vy"] * dt
        dx, dy = ball["x"] - CX, ball["y"] - CY
        dist = math.hypot(dx, dy) or 1
        inner = next((k for k, rg in enumerate(rings) if rg["alive"]), None)
        if inner is None:
            break
        rg = rings[inner]
        if dist + ball["r"] > rg["R"] - 10:
            a = math.atan2(dy, dx)
            if ang_in_gap(a, rg) and dist < rg["R"] + 14:
                pass  # slipping through the gap
            elif dist > rg["R"] + 14:
                rg["alive"] = False   # escaped this ring -> shatter it
                events.append((frame, "break", inner))
                for j in range(rg["n"]):
                    t = rg["rot"] + j / rg["n"] * 2 * math.pi
                    if ang_in_gap(t, rg): continue
                    px, py = CX + rg["R"] * math.cos(t), CY + rg["R"] * math.sin(t)
                    sp = rng.uniform(150, 420)
                    shards.append([px, py, math.cos(t) * sp + rng.uniform(-60, 60), math.sin(t) * sp - rng.uniform(0, 200),
                                   1.0, rg["color"]])
            else:
                nx, ny = dx / dist, dy / dist
                vn = ball["vx"] * nx + ball["vy"] * ny
                if vn > 0:
                    ball["vx"] -= 2 * vn * nx; ball["vy"] -= 2 * vn * ny
                    sp = math.hypot(ball["vx"], ball["vy"])
                    want = max(sp, 720)          # keep it lively
                    ball["vx"] *= want / sp; ball["vy"] *= want / sp
                    ball["vx"] += rng.uniform(-40, 40)
                    events.append((frame, "bounce", inner))
                over = dist + ball["r"] - (rg["R"] - 10)
                ball["x"] -= nx * over; ball["y"] -= ny * over
    for rg in rings:
        rg["rot"] += rg["spd"] / FPS
    img = Image.fromarray(bg.copy()); d = ImageDraw.Draw(img)
    for rg in rings:
        if not rg["alive"]: continue
        for j in range(rg["n"]):
            t = rg["rot"] + (j + 0.5) / rg["n"] * 2 * math.pi
            if ang_in_gap(t, rg): continue
            px, py = CX + rg["R"] * math.cos(t), CY + rg["R"] * math.sin(t)
            c = rg["color"]; dark = tuple(int(v * 0.55) for v in c)
            d.rectangle((px - 11, py - 11, px + 11, py + 11), fill=dark)
            d.rectangle((px - 9, py - 9, px + 9, py + 9), fill=c)
    keep = []
    for s in shards:
        s[3] += GRAV / FPS * 0.9; s[0] += s[2] / FPS; s[1] += s[3] / FPS; s[4] -= 0.025
        if s[4] > 0 and s[1] < H:
            keep.append(s); c = tuple(int(v * s[4] + 14 * (1 - s[4])) for v in s[5])
            d.rectangle((s[0] - 8, s[1] - 8, s[0] + 8, s[1] + 8), fill=c)
    shards = keep
    trail = (trail + [(ball["x"], ball["y"])])[-5:]
    for k, (tx, ty) in enumerate(trail[:-1]):
        a = 0.15 + 0.12 * k; r = ball["r"] * (0.6 + 0.08 * k)
        cc = int(14 + (255 - 14) * a)
        d.ellipse((tx - r, ty - r, tx + r, ty + r), fill=(cc, cc, cc))
    d.ellipse((ball["x"] - ball["r"], ball["y"] - ball["r"], ball["x"] + ball["r"], ball["y"] + ball["r"]), fill=(255, 255, 255))
    left = sum(rg["alive"] for rg in rings)
    if left == 0 and end_frame is None:
        end_frame = frame
    if end_frame is not None:
        a = min(1, (frame - end_frame) / 8)
        box = Image.new("RGBA", (W, H), (0, 0, 0, 0)); bd = ImageDraw.Draw(box)
        bd.rounded_rectangle((110, H * 0.415, W - 110, H * 0.585), radius=40, fill=(10, 10, 14, int(235 * a)))
        bd.text((W / 2, H * 0.45), "ESCAPED!", font=fnt, fill=(255, 255, 255, int(255 * a)), anchor="mt")
        bd.text((W / 2, H * 0.53), f"{NR} rings in {end_frame // FPS}s", font=fnt2, fill=(255, 200, 90, int(255 * a)), anchor="mt")
        img = Image.alpha_composite(img.convert("RGBA"), box).convert("RGB")
        if frame - end_frame > 2.5 * FPS:
            break
    enc.write(np.array(img)); frames_total += 1
enc.close()
# audio: bounce = note by ring (higher as you get out), break = sparkle burst
mix = np.zeros(int(frames_total / FPS * SR) + SR, np.float32)
scale = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21, 24]
nrng = np.random.default_rng(2)
for fr, kind, ring in events:
    i = int(fr / FPS * SR)
    if kind == "bounce":
        add(mix, i, bell(262 * 2 ** (scale[ring % len(scale)] / 12), 0.35, 0.22, 9))
    else:
        for j, st in enumerate((0, 4, 7, 12)):
            add(mix, i + int(j * 0.04 * SR), bell(523 * 2 ** ((scale[ring % len(scale)] + st) / 12), 0.6, 0.16, 6))
        n = int(0.25 * SR); add(mix, i, (nrng.standard_normal(n) * np.exp(-np.arange(n) / SR * 18) * 0.08).astype(np.float32))
if end_frame is not None:
    for j, n in enumerate((523, 659, 784, 1047)):
        add(mix, int((end_frame / FPS + j * 0.09) * SR), bell(n, 1.0, 0.3, 3))
write_wav(S[:-6] + ".wav", mix)
mux(S, S[:-6] + ".wav", S.replace("rings.v.mp4", "demo_rings.mp4"))
print("frames", frames_total, "escaped at", None if end_frame is None else round(end_frame / FPS, 1))
