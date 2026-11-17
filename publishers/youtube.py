"""
YouTube uploader (YouTube Data API v3, videos.insert, resumable upload).

Needs three secrets, created once with scripts/get_youtube_token.py:
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN

Heads-up: until your Google Cloud project passes YouTube's API compliance audit,
YouTube may lock API-uploaded videos to private no matter what privacy you request.
"""
import os

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
KEYS = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")


def configured():
    return all(os.environ.get(k) for k in KEYS)


def post(path, caption, settings):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    body = {
        "snippet": {
            "title": caption["title"],
            "description": caption["description"],
            "tags": caption.get("tags", []),
            "categoryId": settings.get("category_id", "24"),  # 24 = Entertainment
        },
        "status": {
            "privacyStatus": settings.get("privacy", "public"),
            "selfDeclaredMadeForKids": False,
            # Code-drawn animation, not realistic footage of real people/events, so no AI disclosure needed.
            "containsSyntheticMedia": False,
        },
    }
    media = MediaFileUpload(path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    status = resp.get("status", {}).get("privacyStatus")
    if status and status != body["status"]["privacyStatus"]:
        print(f"  note: YouTube set this video to '{status}' (likely the unaudited-project lock)")
    return f"https://youtube.com/shorts/{vid}"
