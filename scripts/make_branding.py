import sys, random, math
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from PIL import Image, ImageDraw, ImageFilter
import brick_breaker_gen as gen

BG = (14, 14, 20)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "branding") + "/"

def hsv(h, s=0.75, v=0.95):
    return gen.hsv(h, s, v)

def brick(d, x, y, w, h, col):
    dark = tuple(int(c * 0.55) for c in col)
    light = tuple(min(255, int(c * 1.25)) for c in col)
    d.rectangle((x, y, x + w - 1, y + h - 1), fill=dark)
    d.rectangle((x + 3, y + 3, x + w - 4, y + h - 4), fill=col)
    d.rectangle((x + 3, y + 3, x + w - 4, y + 3 + max(2, h // 8)), fill=light)

def ball(img, cx, cy, r, trail_dir, color=(255, 255, 255), n=5, step=None):
    step = step or r * 2.2
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    dx, dy = trail_dir
    for k in range(n, 0, -1):
        a = int(255 * (0.12 + 0.1 * (n - k)) )
        x, y = cx - dx * step * k, cy - dy * step * k
        rr = r * (0.75 + 0.05 * (n - k))
        d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=color + (a,))
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((cx - r * 2.2, cy - r * 2.2, cx + r * 2.2, cy + r * 2.2), fill=color + (90,))
    glow = glow.filter(ImageFilter.GaussianBlur(r))
    img.alpha_composite(glow)
    img.alpha_composite(ov)
    ImageDraw.Draw(img).ellipse((cx - r, cy - r, cx + r, cy + r), fill=color + (255,))

# ---------------- avatar: the last brick, with the ball on its way
def avatar(S=800):
    img = Image.new("RGBA", (S, S), BG + (255,))
    d = ImageDraw.Draw(img)
    bw, bh = int(S * 0.30), int(S * 0.15)
    brick(d, (S - bw) // 2, int(S * 0.24), bw, bh, (255, 95, 95))
    # a few broken-brick fragments fading out
    rng = random.Random(3)
    for _ in range(14):
        x = S / 2 + rng.uniform(-S * 0.33, S * 0.33); y = S * 0.3 + rng.uniform(-S * 0.12, S * 0.1)
        if abs(x - S / 2) < bw * 0.6 and abs(y - S * 0.315) < bh: continue
        s = rng.randint(int(S * 0.018), int(S * 0.03)); c = hsv(rng.random())
        d.rectangle((x, y, x + s, y + s), fill=tuple(int(v * 0.5) for v in c))
    # paddle
    pw, ph = int(S * 0.34), int(S * 0.035)
    d.rounded_rectangle(((S - pw) // 2 - int(S*0.06), int(S * 0.76), (S + pw) // 2 - int(S*0.06), int(S * 0.76) + ph), radius=ph // 2, fill=(255, 140, 80))
    ball(img, S * 0.56, S * 0.5, S * 0.042, (0.45, -0.89), n=4, step=S * 0.07)
    return img.convert("RGB")

# ---------------- banner: a wall of bricks being cleared, title on the right
def banner(Wd, Ht, safe=None):
    img = Image.new("RGBA", (Wd, Ht), BG + (255,))
    d = ImageDraw.Draw(img)
    sx0, sy0, sx1, sy1 = safe or (0, 0, Wd, Ht)
    sw, sh = sx1 - sx0, sy1 - sy0
    cell = max(14, int(sh / 15))
    bwid, bhgt = cell * 2, cell
    rng = random.Random(7)
    cols, rows = Wd // bwid + 2, Ht // bhgt + 2
    # bricks fill the canvas; a curved "cleared" channel runs through the left half, text area kept clear
    text_left = sx0 + sw * 0.38
    for r in range(rows):
        for c in range(cols):
            x = c * bwid - (bwid // 2 if r % 2 else 0); y = r * bhgt
            cxn, cyn = (x + bwid / 2), (y + bhgt / 2)
            if cxn > text_left - bwid * 0.5:
                continue  # dark space for the title
            fade = cxn / max(1, text_left)
            hole = math.hypot((cxn - (sx0 + sw * 0.2)) / (sw * 0.16), (cyn - (sy0 + sh * 0.55)) / (sh * 0.36)) < 1
            if hole or rng.random() < 0.08 + 0.55 * fade ** 2:
                continue
            col = hsv((cxn / Wd * 0.9 + cyn / Ht * 0.15) % 1)
            brick(d, x, y, bwid, bhgt, col)
    tx = text_left + sw * 0.03
    room = sx1 - tx - sw * 0.04
    size = int(sh * 0.2)
    while gen.font(size).getlength("No Brick Left Behind") > room: size -= 2
    f1 = gen.font(size)
    size2 = int(size * 0.42)
    while gen.font(size2).getlength("Oddly satisfying brick-breaker battles. New ones daily.") > room: size2 -= 1
    f2 = gen.font(size2)
    d.text((tx, sy0 + sh * 0.47), "No Brick Left Behind", font=f1, fill=(240, 240, 248), anchor="ls")
    d.text((tx, sy0 + sh * 0.66), "Oddly satisfying brick-breaker battles. New ones daily.", font=f2,
           fill=(170, 170, 190), anchor="ls")
    for i, (a, b) in enumerate([((255, 95, 95), "RED"), ((95, 175, 255), "BLUE")]):
        pass
    ball(img, sx0 + sw * 0.2, sy0 + sh * 0.55, sh * 0.045, (0.6, -0.8), n=5, step=sh * 0.07)
    pw = sh * 0.28
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((sx0 + sw * 0.2 - pw / 2 - sh*0.08, sy0 + sh * 0.86, sx0 + sw * 0.2 + pw / 2 - sh*0.08, sy0 + sh * 0.89), radius=6, fill=(255, 140, 80))
    return img.convert("RGB")

avatar(800).save(OUT + "avatar_800.png")
avatar(800).resize((400, 400), Image.LANCZOS).save(OUT + "avatar_400.png")
banner(1500, 500, (0, 0, 1500, 500)).save(OUT + "x_banner_1500x500.png")
# YouTube: 2560x1440, content inside the 1546x423 safe area (centered)
banner(2560, 1440, ((2560 - 1546) // 2, (1440 - 423) // 2, (2560 + 1546) // 2, (1440 + 423) // 2)).save(OUT + "youtube_banner_2560x1440.png")
print("ok")
