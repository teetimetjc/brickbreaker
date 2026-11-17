"""
X (Twitter) poster: chunked video upload on the v2 media endpoint, then POST /2/tweets.

Needs four secrets from your X developer app (OAuth 1.0a, "Read and write" permission):
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET

Cost on pay-per-use: about $0.015 per post plus the upload calls. Keep links OUT of the
text: a post containing a URL is billed at ~$0.20.
"""
import os
import time

UPLOAD_URL = "https://api.x.com/2/media/upload"
TWEET_URL = "https://api.x.com/2/tweets"
KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")
CHUNK = 4 * 1024 * 1024


def configured():
    return all(os.environ.get(k) for k in KEYS)


def _session():
    from requests_oauthlib import OAuth1Session
    return OAuth1Session(os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
                         os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_SECRET"])


def _check(r, step):
    if r.status_code >= 300:
        raise RuntimeError(f"X {step} failed ({r.status_code}): {r.text[:400]}")
    return r.json() if r.content else {}


def upload_video(s, path):
    size = os.path.getsize(path)
    init = _check(s.post(UPLOAD_URL, data={"command": "INIT", "total_bytes": size,
                                           "media_type": "video/mp4", "media_category": "tweet_video"}), "INIT")
    media_id = str(init["data"]["id"])
    with open(path, "rb") as f:
        idx = 0
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            _check(s.post(UPLOAD_URL, data={"command": "APPEND", "media_id": media_id, "segment_index": idx},
                          files={"media": chunk}), f"APPEND {idx}")
            idx += 1
    info = _check(s.post(UPLOAD_URL, data={"command": "FINALIZE", "media_id": media_id}), "FINALIZE")
    proc = info.get("data", {}).get("processing_info")
    waited = 0
    while proc and proc.get("state") in ("pending", "in_progress"):
        wait = proc.get("check_after_secs", 5)
        time.sleep(wait)
        waited += wait
        if waited > 600:
            raise RuntimeError("X video processing timed out")
        st = _check(s.get(UPLOAD_URL, params={"command": "STATUS", "media_id": media_id}), "STATUS")
        proc = st.get("data", {}).get("processing_info")
    if proc and proc.get("state") == "failed":
        raise RuntimeError(f"X video processing failed: {proc.get('error')}")
    return media_id


def post(path, caption, settings):
    s = _session()
    media_id = upload_video(s, path)
    r = _check(s.post(TWEET_URL, json={"text": caption["text"], "media": {"media_ids": [media_id]}}), "create post")
    tid = r["data"]["id"]
    return f"https://x.com/i/status/{tid}"
