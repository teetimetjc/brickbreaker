import sys, random, numpy as np
from common import *
import brick_breaker_gen as gen
FPS = gen.FPS
G = 6  # sand grain size in px

class SandRenderer(gen.Renderer):
    """Broken bricks crumble into grains that fall and pile up in their colors along the floor."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        L = self.L
        self.x0, self.x1 = L.ox + L.cell, L.ox + (L.cols - 1) * L.cell
        self.floor = L.oy + (L.rows - 1) * L.cell          # pile sits on the floor row
        self.ncol = (self.x1 - self.x0) // G
        self.piles = [[] for _ in range(self.ncol)]           # per column: list of colors, bottom first
        self.grains = []                                      # [x, y, vy, color]
        self.rng = random.Random(7)

    def _settle(self, col, color):
        # slide down to a lower neighbour so the pile forms slopes, like real sand
        for _ in range(12):
            h = len(self.piles[col])
            opts = [c for c in (col - 1, col + 1) if 0 <= c < self.ncol and len(self.piles[c]) < h - 1]
            if not opts:
                break
            col = self.rng.choice(opts)
        self.piles[col].append(color)

    def frame(self, overlay=None):
        L, cs = self.L, self.L.cell
        for r, c in self.sim.changed:
            if self.sim.g[r, c] == gen.EMPTY:
                col = np.array(self.brick_color(r), np.float32)
                for _ in range(10):
                    x = L.ox + c * cs + self.rng.uniform(0, cs)
                    y = L.oy + r * cs + self.rng.uniform(0, cs)
                    shade = np.clip(col * self.rng.uniform(0.8, 1.15), 0, 255).astype(np.uint8)
                    self.grains.append([x, y, self.rng.uniform(0, 3), shade])
        f = super().frame(None)
        keep = []
        for g in self.grains:
            g[2] += 0.9                     # gravity
            g[1] += g[2]
            ci = int((g[0] - self.x0) // G)
            ci = min(max(ci, 0), self.ncol - 1)
            top = self.floor - len(self.piles[ci]) * G
            if g[1] >= top - G:
                self._settle(ci, g[3])
            else:
                keep.append(g)
                xi, yi = int(g[0]), int(g[1])
                f[yi:yi + G - 1, xi:xi + G - 1] = g[3]
        self.grains = keep
        for ci, stack in enumerate(self.piles):
            x = self.x0 + ci * G
            for k, color in enumerate(stack):
                y = self.floor - (k + 1) * G
                f[y:y + G - 1, x:x + G - 1] = color
        if overlay is not None:
            img, a = overlay
            f = (f.astype(np.float32) * (1 - a) + img * a).astype(np.uint8)
        return f

def sand_audio(events, total_frames, L, end_frame, won, path, sr=SR):
    # soft trickling hiss for each break + a gentle low tone; much quieter than the normal blips
    mix = np.zeros(int(total_frames / FPS * SR) + SR, np.float32)
    rng = np.random.default_rng(1)
    last = -1
    for fr, kind, row in events:
        t = fr / FPS
        if kind == "brick" and t - last > 0.02:
            last = t
            n = int(0.35 * SR)
            noise = rng.standard_normal(n).astype(np.float32)
            env = np.exp(-np.arange(n) / SR * 9)
            # crude low-pass: moving average
            k = 6
            noise = np.convolve(noise, np.ones(k) / k, mode="same")
            add(mix, int(t * SR), noise * env * 0.07)
            add(mix, int(t * SR), bell(220 * 2 ** (rng.integers(0, 12) / 12), 0.3, 0.05, 10))
    if end_frame is not None:
        for j, n in enumerate((523, 659, 784)):
            add(mix, int((end_frame / FPS + j * 0.12) * SR), bell(n, 1.0, 0.25, 3))
    write_wav(path, mix)

gen.Renderer = SandRenderer
gen.build_audio = sand_audio
S = "out/"
cfg = gen.default_cfg(pattern="rings", obstacle="none", palette="sunset", lose=False, target=24, max_cell=30, seed=21,
                      outdir=S, title="Sand bricks")
cfg["card_extras"] = None
gen.make_video(cfg, S + "demo_sand.mp4")
