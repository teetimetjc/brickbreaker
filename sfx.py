"""Small shared helpers for the newer styles (ring escape, brick drop): synth sounds, wav, ffmpeg encode/mux."""
import subprocess
import wave

import numpy as np

SR = 44100


def write_wav(path, mix):
    pcm = (np.tanh(mix * 1.1) * 0.85 * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())


def add(mix, i, w):
    if 0 <= i < len(mix):
        mix[i:i + len(w)] += w[: max(0, len(mix) - i)]


def bell(freq, dur=0.6, amp=0.3, decay=5.0):
    t = np.arange(int(dur * SR)) / SR
    w = (np.sin(2 * np.pi * freq * t) + 0.45 * np.sin(4 * np.pi * freq * t) * np.exp(-t * 3)
         + 0.2 * np.sin(6 * np.pi * freq * t) * np.exp(-t * 6))
    return (w * np.exp(-t * decay) * amp * np.minimum(1, t / 0.004)).astype(np.float32)


def noise_burst(dur, amp, decay, seed=0):
    n = int(dur * SR)
    return (np.random.default_rng(seed).standard_normal(n) * np.exp(-np.arange(n) / SR * decay) * amp).astype(np.float32)


def win_chime(mix, t):
    for j, f in enumerate((523, 659, 784, 1047)):
        add(mix, int((t + j * 0.09) * SR), bell(f, 1.0, 0.3, 3))


class Encoder:
    def __init__(self, path, W=1080, H=1920, fps=30):
        self.p = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
             "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             path], stdin=subprocess.PIPE)
        self.n = 0

    def write(self, frame):
        self.p.stdin.write(np.ascontiguousarray(frame).tobytes())
        self.n += 1

    def close(self):
        self.p.stdin.close()
        if self.p.wait() != 0:
            raise RuntimeError("ffmpeg video encode failed")


def mux(video, audio, out):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-i", audio, "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out])
    if r.returncode != 0:
        raise RuntimeError("ffmpeg mux failed")
