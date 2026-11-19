"""
TikTok publisher: sends each video to the connected account's TikTok INBOX as a draft (Content Posting API,
"Upload to TikTok", scope video.upload). The creator gets a notification in the TikTok app, adds a sound /
caption and posts it. Works from a Sandbox app (no app review) as long as the account is a sandbox target user.

Secrets: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET (from the app's Sandbox credentials).
Token:   data/tiktok_token.enc - the OAuth tokens, encrypted with a key derived from TIKTOK_CLIENT_SECRET, committed
         by the workflow so refreshed tokens survive between runs. Created once by scripts/tiktok_connect.py.

Note: inbox uploads can't carry a caption; the caption is written to captions.txt / the run summary instead.
"""
import base64
import hashlib
import json
import os
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(HERE, "data", "tiktok_token.enc")
REDIRECT_URI = "https://teetimetjc.github.io/nobrick/callback.html"
SCOPES = "user.info.basic,video.upload"
API = "https://open.tiktokapis.com/v2"
KEYS = ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET")
SINGLE_CHUNK_MAX = 64 * 1024 * 1024
CHUNK = 10 * 1024 * 1024


def configured():
    return all(os.environ.get(k, "").strip() for k in KEYS) and os.path.exists(TOKEN_FILE)


def _env(k):
    return os.environ[k].strip()


def _fernet():
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(b"nobrick-tiktok:" + _env("TIKTOK_CLIENT_SECRET").encode()).digest())
    return Fernet(key)


def save_token(tok):
    tok = dict(tok)
    now = time.time()
    tok.setdefault("obtained_at", now)
    if "expires_in" in tok:
        tok["access_expires_at"] = now + int(tok["expires_in"]) - 300
    if "refresh_expires_in" in tok:
        tok["refresh_expires_at"] = now + int(tok["refresh_expires_in"])
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "wb") as f:
        f.write(_fernet().encrypt(json.dumps(tok).encode()))


def load_token():
    with open(TOKEN_FILE, "rb") as f:
        return json.loads(_fernet().decrypt(f.read()))


def _oauth(data):
    import requests
    r = requests.post(f"{API}/oauth/token/", data={"client_key": _env("TIKTOK_CLIENT_KEY"),
                                                    "client_secret": _env("TIKTOK_CLIENT_SECRET"), **data},
                      headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    body = r.json() if r.content else {}
    if r.status_code >= 300 or "access_token" not in body:
        raise RuntimeError(f"TikTok token request failed ({r.status_code}): {json.dumps(body)[:400]}")
    return body


def authorize_url(client_key, state="nobrick"):
    from urllib.parse import urlencode
    return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
        "client_key": client_key, "scope": SCOPES, "response_type": "code",
        "redirect_uri": REDIRECT_URI, "state": state})


def exchange_code(code):
    tok = _oauth({"code": code, "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI})
    save_token(tok)
    return tok


def access_token():
    tok = load_token()
    if time.time() < tok.get("access_expires_at", 0):
        return tok["access_token"]
    new = _oauth({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    save_token(new)  # TikTok may rotate the refresh token; the workflow commits the updated file
    return new["access_token"]


def _api(method, path, token, **kw):
    import requests
    r = requests.request(method, f"{API}{path}", headers={"Authorization": f"Bearer {token}",
                                                         "Content-Type": "application/json; charset=UTF-8"},
                         timeout=60, **kw)
    body = r.json() if r.content else {}
    err = body.get("error", {})
    if r.status_code >= 300 or (err.get("code") not in (None, "ok")):
        raise RuntimeError(f"TikTok {path} failed ({r.status_code}): {json.dumps(body)[:400]}")
    return body.get("data", {})


def whoami():
    return _api("GET", "/user/info/?fields=open_id,display_name", access_token()).get("user", {})


def post(path, caption, settings):
    import requests
    token = access_token()
    size = os.path.getsize(path)
    if size <= SINGLE_CHUNK_MAX:
        chunk, count = size, 1
    else:  # TikTok: chunks of 5-64 MB, the last one absorbs the remainder
        chunk, count = CHUNK, size // CHUNK
    data = _api("POST", "/post/publish/inbox/video/init/", token, json={"source_info": {
        "source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}})
    upload_url, publish_id = data["upload_url"], data["publish_id"]
    with open(path, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            f.seek(start)
            blob = f.read(end - start + 1)
            r = requests.put(upload_url, data=blob, timeout=300, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(blob)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            if r.status_code >= 300:
                raise RuntimeError(f"TikTok upload chunk {i} failed ({r.status_code}): {r.text[:300]}")
    status = "PROCESSING"
    for _ in range(30):
        time.sleep(4)
        st = _api("POST", "/post/publish/status/fetch/", token, json={"publish_id": publish_id})
        status = st.get("status", status)
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            break
        if status == "FAILED":
            raise RuntimeError(f"TikTok processing failed: {st.get('fail_reason')}")
    return f"tiktok-inbox:{publish_id} ({status})"
