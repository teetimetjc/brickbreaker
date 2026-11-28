"""
YouTube uploader (YouTube Data API v3, videos.insert, resumable upload).

Needs three secrets, created once with scripts/get_youtube_token.py:
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN

Heads-up: until your Google Cloud project passes YouTube's API compliance audit,
YouTube may lock API-uploaded videos to private no matter what privacy you request.
"""
import os

# upload = post videos; force-ssl = comment as the channel and add videos to playlists. A refresh token made with
# only the upload scope still uploads fine; the extras are then skipped with a warning.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
KEYS = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")


def configured():
    return all(os.environ.get(k) for k in KEYS)


def post(path, caption, settings):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"].strip(),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"].strip(),
        client_secret=os.environ["YT_CLIENT_SECRET"].strip(),
    )
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    body = {
        "snippet": {
            "title": caption["title"],
            "description": caption["description"],
            "tags": caption.get("tags", []),
            "categoryId": settings.get("category_id", "24"),  # 24 = Entertainment
            "defaultLanguage": settings.get("language", "en"),        # tells YouTube who to show it to
            "defaultAudioLanguage": settings.get("language", "en"),
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
    extras(yt, vid, caption)
    status = resp.get("status", {}).get("privacyStatus")
    if status and status != body["status"]["privacyStatus"]:
        print(f"  note: YouTube set this video to '{status}' (likely the unaudited-project lock)")
    return f"https://youtube.com/shorts/{vid}"


_playlist_cache = {}


def _playlist_id(yt, title):
    """Find the channel's playlist with this exact title, creating it (public) if missing."""
    if title in _playlist_cache:
        return _playlist_cache[title]
    req = yt.playlists().list(part="snippet", mine=True, maxResults=50)
    while req is not None:
        resp = req.execute()
        for it in resp.get("items", []):
            _playlist_cache[it["snippet"]["title"]] = it["id"]
        req = yt.playlists().list_next(req, resp)
    if title not in _playlist_cache:
        made = yt.playlists().insert(part="snippet,status", body={
            "snippet": {"title": title, "description": f"{title} from No Brick Left Behind. New ones every day."},
            "status": {"privacyStatus": "public"}}).execute()
        _playlist_cache[title] = made["id"]
        print(f"  created playlist '{title}'")
    return _playlist_cache[title]


def extras(yt, vid, caption):
    """Add the video to its playlist and post the channel's comment. Never fails the upload."""
    if caption.get("playlist"):
        try:
            pid = _playlist_id(yt, caption["playlist"])
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
            print(f"  added to playlist '{caption['playlist']}'")
        except Exception as e:  # e.g. refresh token made without the force-ssl scope
            print(f"  note: playlist skipped ({str(e)[:160]})")
    if caption.get("comment"):
        try:
            yt.commentThreads().insert(part="snippet", body={"snippet": {
                "videoId": vid, "topLevelComment": {"snippet": {"textOriginal": caption["comment"]}}}}).execute()
            print("  posted channel comment")
        except Exception as e:
            print(f"  note: comment skipped ({str(e)[:160]})")


def set_thumbnail(video_id, image_path):
    """Custom thumbnail (needs a phone-verified channel). Works with the youtube.upload scope."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"].strip(),
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"].strip(), client_secret=os.environ["YT_CLIENT_SECRET"].strip())
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(image_path, mimetype="image/jpeg")).execute()
