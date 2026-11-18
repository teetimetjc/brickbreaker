"""
X (Twitter) poster: chunked video upload, then POST /2/tweets (optionally as a quote post).

Needs four secrets from your X developer app (OAuth 1.0a, "Read and write" permission):
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET

Upload uses the current v2 protocol (/2/media/upload/initialize, /{id}/append, /{id}/finalize).
If X rejects that, it falls back to the legacy v1.1 chunked upload, which some OAuth 1.0a apps
still need. On a 401 it checks GET /2/users/me once, so the error says whether the keys themselves work.

Cost on pay-per-use: about $0.015 per post plus the upload calls. Keep links OUT of the
text: a post containing a URL is billed at ~$0.20.
"""
import os
import re
import time

API = "https://api.x.com/2"
V2_UPLOAD = f"{API}/media/upload"
V1_UPLOAD = "https://upload.twitter.com/1.1/media/upload.json"
TWEET_URL = f"{API}/tweets"
KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")
CHUNK = 4 * 1024 * 1024


class XError(RuntimeError):
    def __init__(self, step, r):
        self.status = r.status_code
        super().__init__(f"X {step} failed ({r.status_code}): {r.text[:400]}")


def configured():
    return all(os.environ.get(k, "").strip() for k in KEYS)


def _session():
    from requests_oauthlib import OAuth1Session
    k = [os.environ[n].strip() for n in KEYS]  # stray spaces/newlines from copy-paste break the signature
    return OAuth1Session(k[0], k[1], k[2], k[3])


def _check(r, step):
    if r.status_code >= 300:
        raise XError(step, r)
    return r.json() if r.content else {}


def _wait_processing(s, media_id, proc, status_get):
    waited = 0
    while proc and proc.get("state") in ("pending", "in_progress"):
        wait = proc.get("check_after_secs", 5)
        time.sleep(wait)
        waited += wait
        if waited > 600:
            raise RuntimeError("X video processing timed out")
        proc = status_get()
    if proc and proc.get("state") == "failed":
        raise RuntimeError(f"X video processing failed: {proc.get('error')}")


def _chunks(path):
    with open(path, "rb") as f:
        idx = 0
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                return
            yield idx, chunk
            idx += 1


def upload_v2(s, path):
    size = os.path.getsize(path)
    init = _check(s.post(f"{V2_UPLOAD}/initialize", json={
        "media_type": "video/mp4", "total_bytes": size, "media_category": "tweet_video"}), "upload initialize")
    media_id = str(init["data"]["id"])
    for idx, chunk in _chunks(path):
        _check(s.post(f"{V2_UPLOAD}/{media_id}/append", data={"segment_index": idx},
                      files={"media": ("chunk", chunk, "application/octet-stream")}), f"upload append {idx}")
    info = _check(s.post(f"{V2_UPLOAD}/{media_id}/finalize"), "upload finalize")

    def status():
        st = _check(s.get(V2_UPLOAD, params={"command": "STATUS", "media_id": media_id}), "upload status")
        return st.get("data", {}).get("processing_info")

    _wait_processing(s, media_id, info.get("data", {}).get("processing_info"), status)
    return media_id


def upload_v1(s, path):
    size = os.path.getsize(path)
    init = _check(s.post(V1_UPLOAD, data={"command": "INIT", "total_bytes": size,
                                          "media_type": "video/mp4", "media_category": "tweet_video"}), "v1.1 INIT")
    media_id = init["media_id_string"]
    for idx, chunk in _chunks(path):
        _check(s.post(V1_UPLOAD, data={"command": "APPEND", "media_id": media_id, "segment_index": idx},
                      files={"media": chunk}), f"v1.1 APPEND {idx}")
    info = _check(s.post(V1_UPLOAD, data={"command": "FINALIZE", "media_id": media_id}), "v1.1 FINALIZE")

    def status():
        return _check(s.get(V1_UPLOAD, params={"command": "STATUS", "media_id": media_id}),
                      "v1.1 STATUS").get("processing_info")

    _wait_processing(s, media_id, info.get("processing_info"), status)
    return media_id


def whoami(s):
    """Cheap key check: which account do these keys post as? Raises with a plain explanation if they don't work."""
    r = s.get(f"{API}/users/me")
    if r.status_code == 401:
        raise RuntimeError(
            "X rejected the keys themselves (401 on /2/users/me). Re-copy all four into the GitHub secrets: "
            "X_API_KEY = Consumer Key, X_API_SECRET = Consumer Secret, X_ACCESS_TOKEN = Access Token (starts "
            "with numbers and a dash), X_ACCESS_SECRET = Access Token Secret. If you regenerated the Consumer "
            "Key after making the Access Token, regenerate the Access Token too. Also check the account has credit.")
    return _check(r, "users/me")["data"]["username"]


def upload_video(s, path):
    try:
        return upload_v2(s, path)
    except XError as e:
        print(f"  v2 upload failed ({e}); trying legacy v1.1 upload")
        if e.status == 401:
            print(f"  keys work for @{whoami(s)}")  # raises a clear message if the keys are the problem
        return upload_v1(s, path)


def tweet_id(url_or_id):
    """'https://x.com/someone/status/123?s=20' or '123' -> '123'."""
    m = re.search(r"/status(?:es)?/(\d+)", url_or_id or "") or re.fullmatch(r"\s*(\d{5,25})\s*", url_or_id or "")
    if not m:
        raise ValueError(f"not an X post link or id: {url_or_id!r}")
    return m.group(1)


def post(path, caption, settings):
    """caption: {"text": ..., "quote": optional post URL/id to quote}."""
    s = _session()
    media_id = upload_video(s, path)
    body = {"text": caption["text"], "media": {"media_ids": [media_id]}}
    if caption.get("quote"):
        body["quote_tweet_id"] = tweet_id(caption["quote"])
    r = _check(s.post(TWEET_URL, json=body), "create post")
    tid = r["data"]["id"]
    return f"https://x.com/i/status/{tid}"
