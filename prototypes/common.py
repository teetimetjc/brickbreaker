import sys, wave, subprocess, numpy as np
sys.path.insert(0, "/home/user/brickbreaker")
SR = 44100
def write_wav(path, mix):
    pcm = (np.tanh(mix * 1.1) * 0.85 * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR); wf.writeframes(pcm.tobytes())
def add(mix, i, w):
    if i < 0 or i >= len(mix): return
    mix[i:i + len(w)] += w[: max(0, len(mix) - i)]
def bell(freq, dur=0.6, amp=0.3, decay=5.0):
    t = np.arange(int(dur * SR)) / SR
    w = (np.sin(2*np.pi*freq*t) + 0.45*np.sin(2*np.pi*2*freq*t)*np.exp(-t*3) + 0.2*np.sin(2*np.pi*3*freq*t)*np.exp(-t*6))
    att = np.minimum(1, t / 0.004)
    return (w * np.exp(-t * decay) * amp * att).astype(np.float32)
def mux(video, audio, out):
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",video,"-i",audio,"-map","0:v","-map","1:a","-c:v","copy",
                    "-c:a","aac","-b:a","160k","-shortest","-movflags","+faststart",out], check=True)
class Encoder:
    def __init__(self, path, W=1080, H=1920, fps=30):
        self.p = subprocess.Popen(["ffmpeg","-y","-loglevel","error","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}",
            "-r",str(fps),"-i","-","-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",path], stdin=subprocess.PIPE)
        self.n = 0
    def write(self, f): self.p.stdin.write(np.ascontiguousarray(f).tobytes()); self.n += 1
    def close(self): self.p.stdin.close(); self.p.wait()
