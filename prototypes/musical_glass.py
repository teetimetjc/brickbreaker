import sys, random, numpy as np
from common import *
import brick_breaker_gen as gen
FPS = gen.FPS
# Jingle Bells (public domain, J. Pierpont 1857) - chorus, as MIDI notes
JB = [64,64,64, 64,64,64, 64,67,60,62,64, 65,65,65,65, 65,64,64,64,64, 64,62,62,64,62,67,
      64,64,64, 64,64,64, 64,67,60,62,64, 65,65,65,65, 65,64,64,64,64, 67,67,65,62,60]
def midi(n): return 440 * 2 ** ((n - 69) / 12)

def melody_audio(events, total_frames, L, end_frame, won, path, sr=SR):
    mix = np.zeros(int(total_frames / FPS * SR) + SR, np.float32)
    k, last = 0, -1
    for fr, kind, row in events:
        t = fr / FPS
        if kind != "brick" or t - last < 0.24:  # steady-ish tempo: skip hits that come too fast
            continue
        last = t
        add(mix, int(t * SR), bell(midi(JB[k % len(JB)] + 12), 0.7, 0.32, 4.5))
        k += 1
    if end_frame is not None:
        for j, n in enumerate((72, 76, 79, 84)):
            add(mix, int((end_frame / FPS + j * 0.1) * SR), bell(midi(n), 1.0, 0.3, 3))
    write_wav(path, mix)

def glass_clink(freq, amp=0.22):
    t = np.arange(int(0.45 * SR)) / SR
    w = sum(a * np.sin(2*np.pi*freq*m*t) * np.exp(-t*d) for m, a, d in ((1,1,9),(2.76,0.5,14),(5.4,0.3,22),(8.9,0.15,30)))
    return (w * amp).astype(np.float32)

def glass_audio(events, total_frames, L, end_frame, won, path, sr=SR):
    mix = np.zeros(int(total_frames / FPS * SR) + SR, np.float32)
    rng, last = random.Random(3), -1
    for fr, kind, row in events:
        t = fr / FPS
        if kind == "brick":
            if t - last < 0.03: continue
            last = t
            add(mix, int(t * SR), glass_clink(rng.uniform(1700, 3200)))
        elif kind == "paddle":
            add(mix, int(t * SR), glass_clink(600, 0.12))
    if end_frame is not None:
        for j in range(6):
            add(mix, int((end_frame / FPS + j * 0.07) * SR), glass_clink(2000 + j * 350, 0.2))
    write_wav(path, mix)

class GlassRenderer(gen.Renderer):
    def paint(self, r, c):
        L, cs = self.L, self.L.cell
        y0, x0 = L.oy + r * cs, L.ox + c * cs
        v = self.sim.g[r, c]
        blk = self.board[y0:y0 + cs, x0:x0 + cs]
        if v == gen.BRICK:
            t = (r - L.brick_top) / max(1, L.brick_bot - L.brick_top)
            base = np.array(gen.lerp((150, 230, 255), (175, 160, 255), min(max(t, 0), 1)), np.float32)
            bg = self.BG.astype(np.float32)
            blk[:] = (bg * 0.55 + base * 0.45).astype(np.uint8)              # see-through body
            blk[1:-1, 1:2] = blk[1:2, 1:-1] = np.minimum(base * 1.15, 255).astype(np.uint8)  # bright edges
            blk[2:5, 3:cs // 2] = 245                                          # glint
        else:
            super().paint(r, c)

def run(kind, out, seed):
    S = "out/"
    if kind == "musical":
        gen.build_audio = melody_audio
        cfg = gen.default_cfg(pattern="diamond", obstacle="none", palette="red", lose=False, max_len=40,
                              target=22, cell=36, seed=seed, outdir=S, title="Guess the song")
    else:
        gen.build_audio = glass_audio
        gen.Renderer = GlassRenderer
        cfg = gen.default_cfg(pattern="heart", obstacle="none", palette="ocean", lose=False, target=22, max_cell=24,
                              seed=seed, outdir=S, title="Glass edition")
    cfg["card_extras"] = None
    gen.make_video(cfg, S + out)

if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], int(sys.argv[3]))
