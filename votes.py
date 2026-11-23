#!/usr/bin/env python3
"""
VIEWER COLOR VOTE: before a color battle is rendered, count the colors viewers named in YouTube comments since the
last voted battle, and put the most-picked color into the battle (the runner-up, if it has votes, is the opponent).
The mid-video banner says "SUBSCRIBE & PICK THE NEXT COLOR" - this is what makes that true.

  python3 votes.py            # print the current tally (needs the YT_* secrets)

Rules: one vote per person per color per tally; the channel's own comments don't count; replies count (most votes
land as replies to the channel's "Team Red or Team Blue?" comment); a comment naming two colors votes for both.
The battle's WINNER is still decided by the physics, never by the vote.
"""
import csv
import datetime as dt
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
POSTS = os.path.join(HERE, "data", "posts.csv")

COLORS = {
    "RED": [r"\bred\b", "🔴", "🟥"],  # no ❤: a red heart usually means "love it", not a vote
    "BLUE": [r"\bblue\b", "🔵", "💙", "🟦"],
    "GREEN": [r"\bgreen\b", r"\bmint\b", "🟢", "💚", "🟩"],
    "PURPLE": [r"\bpurple\b", r"\bgrape\b", "🟣", "💜", "🟪"],
    "YELLOW": [r"\byellow\b", r"\bgold\b", "🟡", "💛", "🟨"],
}
_RX = {c: re.compile("|".join(p), re.I) for c, p in COLORS.items()}


def colors_in(text):
    return [c for c, rx in _RX.items() if rx.search(text or "")]


def _parse(ts):
    return dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)


def window(max_days=10):
    """(video ids to read, count comments after this time) - since the last voted battle, at most max_days back."""
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=max_days)
    rows = []
    if os.path.exists(POSTS):
        with open(POSTS, newline="") as f:
            rows = list(csv.DictReader(f))
    for r in rows:
        if r.get("vote"):
            try:
                since = max(since, dt.datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc))
            except ValueError:
                pass
    vids = []
    for r in rows:
        m = re.search(r"(?:shorts/|v=)([A-Za-z0-9_-]{11})", r.get("youtube_url") or "")
        try:
            when = dt.datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc)
        except (KeyError, ValueError):
            continue
        if m and when > now - dt.timedelta(days=max_days):
            vids.append(m.group(1))
    return vids, since


def _service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    c = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"].strip(),
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.environ["YT_CLIENT_ID"].strip(), client_secret=os.environ["YT_CLIENT_SECRET"].strip())
    return build("youtube", "v3", credentials=c, cache_discovery=False)


def fetch_comments(yt, vids):
    """Yield (author_channel_id, text, published_at) for every comment + reply on these videos."""
    for vid in vids:
        try:
            req = yt.commentThreads().list(part="snippet,replies", videoId=vid, maxResults=100, textFormat="plainText")
            while req is not None:
                resp = req.execute()
                for t in resp.get("items", []):
                    top = t["snippet"]["topLevelComment"]["snippet"]
                    yield top.get("authorChannelId", {}).get("value"), top.get("textDisplay", ""), top["publishedAt"]
                    replies = t.get("replies", {}).get("comments", [])
                    if t["snippet"].get("totalReplyCount", 0) > len(replies):
                        replies = yt.comments().list(part="snippet", parentId=t["id"], maxResults=100,
                                                     textFormat="plainText").execute().get("items", [])
                    for rp in replies:
                        s = rp["snippet"]
                        yield s.get("authorChannelId", {}).get("value"), s.get("textDisplay", ""), s["publishedAt"]
                req = yt.commentThreads().list_next(req, resp)
        except Exception as e:  # comments off / video gone: skip it
            print(f"  votes: can't read comments on {vid} ({str(e)[:100]})")


def tally(max_days=10):
    """{COLOR: votes} from viewers' comments since the last voted battle. {} if YouTube isn't configured."""
    if not all(os.environ.get(k, "").strip() for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")):
        return {}
    yt = _service()
    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    vids, since = window(max_days)
    seen, counts = set(), {}
    for author, text, published in fetch_comments(yt, vids):
        if author == me or _parse(published) <= since:
            continue
        for c in colors_in(text):
            if (author, c) not in seen:
                seen.add((author, c))
                counts[c] = counts.get(c, 0) + 1
    return counts


def pick(counts, rng, min_votes=1):
    """(voted color, runner-up or None) - ties broken at random. None if nobody voted."""
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], rng.random()))
    if not ranked or ranked[0][1] < min_votes:
        return None, None
    second = ranked[1][0] if len(ranked) > 1 and ranked[1][1] >= min_votes else None
    return ranked[0][0], second


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    vids, since = window()
    print(f"reading {len(vids)} videos, votes after {since:%Y-%m-%d %H:%M} UTC")
    print(tally() or "no votes (or no YouTube keys)")
