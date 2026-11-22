#!/usr/bin/env python3
"""
Mid-video SUBSCRIBE banner: a red pill with a white play icon that pops in for ~2.5 s around 40% of the video,
so the >50% of viewers who swipe away before the end card still see the ask. Applied after rendering with ffmpeg
(re-encodes the video only, the audio is copied), so it works for every style.

  python3 banner.py in.mp4 out.mp4 --text "SUBSCRIBE & PICK THE NEXT COLOR"
"""
import argparse
import json
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw

import brick_breaker_gen as gen

YT_RED = (230, 33, 23)


def banner_png(text, W, path):
    """Red pill, white rounded 'play' badge on the left, bold white text. Sized from the video width."""
    fs = int(W * 0.042)
    f = gen.font(fs)
    while f.getlength(text) > W * 0.6 and fs > 20:  # stay inside the 11.5% side margins with room for the icon
        fs -= 2
        f = gen.font(fs)
    h = int(fs * 2.1)
    icon = int(h * 0.62)
    pad = int(h * 0.38)
    w = int(pad + icon + pad * 0.8 + f.getlength(text) + pad * 1.2)
    sh = int(h * 0.12)                                     # soft drop shadow so it reads on light and dark scenes
    img = Image.new("RGBA", (w + sh, h + sh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((sh, sh, w + sh - 1, h + sh - 1), radius=h // 2, fill=(0, 0, 0, 110))
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=YT_RED + (255,), outline=(255, 255, 255, 255),
                        width=max(3, h // 18))
    ix, iy = pad, (h - icon) // 2
    d.rounded_rectangle((ix, iy, ix + icon, iy + icon), radius=icon // 4, fill=(255, 255, 255, 255))
    t = icon * 0.28
    cx, cy = ix + icon / 2 + t * 0.15, iy + icon / 2
    d.polygon([(cx - t, cy - t * 1.15), (cx - t, cy + t * 1.15), (cx + t * 1.25, cy)], fill=YT_RED + (255,))
    d.text((ix + icon + pad * 0.8, h / 2), text, font=f, fill=(255, 255, 255, 255), anchor="lm")
    img.save(path)
    return img.size


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    return j["streams"][0]["width"], j["streams"][0]["height"], float(j["format"]["duration"])


def pick_time(duration, end_at=None, frac=0.4, show=2.5):
    """~40% in, but at least 5 s in and finished well before the ending / end card."""
    stop = (end_at if end_at else duration - 3) - 1.5
    return max(0.0, min(max(5.0, duration * frac), stop - show))


def add_banner(src, dst, text, at=None, show=2.5, y_frac=0.085, end_at=None):
    """Overlay the banner on src -> dst. Returns the start time used (None if the video is too short)."""
    W, H, dur = probe(src)
    if dur < 12:
        return None
    at = pick_time(dur, end_at, show=show) if at is None else at
    with tempfile.TemporaryDirectory() as td:
        png = os.path.join(td, "banner.png")
        bw, bh = banner_png(text, W, png)
        x, y = (W - bw) // 2, int(H * y_frac)
        fade = 0.25
        # pop in: fade + slide down a few px; fade out at the end
        filt = (f"[1:v]format=rgba,fade=t=in:st={at:.2f}:d={fade}:alpha=1,"
                f"fade=t=out:st={at + show - fade:.2f}:d={fade}:alpha=1[b];"
                f"[0:v][b]overlay=x={x}:y='{y}-12*max(0,1-(t-{at:.2f})/{fade})':"
                f"enable='between(t,{at:.2f},{at + show:.2f})':shortest=1[v]")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-loop", "1", "-framerate", "30",
                            "-i", png, "-filter_complex", filt, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264",
                            "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest",
                            "-movflags", "+faststart", dst])
        if r.returncode:
            raise RuntimeError("ffmpeg banner overlay failed")
    return at


def apply_in_place(path, text, **kw):
    tmp = path[:-4] + ".banner.tmp.mp4"
    at = add_banner(path, tmp, text, **kw)
    if at is None:
        return None
    os.replace(tmp, path)
    return at


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--text", default="SUBSCRIBE FOR MORE")
    ap.add_argument("--at", type=float, default=None)
    a = ap.parse_args()
    print(f"banner at {add_banner(a.src, a.dst, a.text, at=a.at)}s")


if __name__ == "__main__":
    main()
