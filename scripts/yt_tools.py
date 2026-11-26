#!/usr/bin/env python3
"""
YouTube helper jobs (run by .github/workflows/youtube-tools.yml; needs YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN).

  python3 scripts/yt_tools.py check      # which scopes the refresh token has + channel stats
  python3 scripts/yt_tools.py backfill   # add every logged upload to its playlist + post the channel comment if missing
  python3 scripts/yt_tools.py report     # per-video analytics joined with data/posts.csv -> data/analytics/<date>.csv

The report uses the YouTube Analytics API (scope yt-analytics.readonly) for watch time / average view duration /
retention / subs gained, plus live view counts from the Data API (Analytics lags ~2 days).
"""
import argparse
import csv
import datetime as dt
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from publishers import youtube  # noqa: E402

POSTS = os.path.join(HERE, "data", "posts.csv")
OUTDIR = os.path.join(HERE, "data", "analytics")


def creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    c = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"].strip(),
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.environ["YT_CLIENT_ID"].strip(), client_secret=os.environ["YT_CLIENT_SECRET"].strip())
    c.refresh(Request())
    return c


def data_api(c):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=c, cache_discovery=False)


def video_id(url):
    m = re.search(r"(?:shorts/|v=)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def posts():
    with open(POSTS, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["video_id"] = video_id(r.get("youtube_url"))
    return [r for r in rows if r["video_id"]]


def summary(text):
    print(text)
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a") as f:
            f.write(text + "\n")


# ---------------------------------------------------------------- check
def check():
    import requests
    c = creds()
    info = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": c.token}, timeout=30).json()
    scopes = info.get("scope", "").split()
    summary("## Token scopes")
    for s in ("youtube.upload", "youtube.force-ssl", "yt-analytics.readonly"):
        ok = any(x.endswith("/" + s) for x in scopes)
        summary(f"- {'✅' if ok else '❌'} {s}")
    ch = data_api(c).channels().list(part="snippet,statistics", mine=True).execute()["items"][0]
    st = ch["statistics"]
    summary(f"\n**{ch['snippet']['title']}**: {st.get('subscriberCount')} subscribers, {st.get('viewCount')} views, "
            f"{st.get('videoCount')} videos")


# ---------------------------------------------------------------- backfill
def comment_for(row, rng):
    sys.path.insert(0, HERE)
    import pipeline
    style = pipeline.style_of(row)
    if style == "episode":
        return "Which color are you backing for next week's episode? 🔴🔵🟡🟢🟣"
    meta = dict(mode=style, outcome=row.get("outcome") or "win")
    if style == "battle":
        meta["teams"] = row["palette"].split("-vs-")
    if style == "normal":
        meta["outcome"] = "lose" if row.get("outcome") == "lose" else "win"
        meta["cleared_pct"] = int(float(row.get("cleared_pct") or 100))
    return pipeline.channel_comment(meta, rng)


def retry(fn, what, tries=4):
    import time
    for i in range(tries):
        try:
            fn()
            return True
        except Exception as e:  # new playlists return 404/409 for a little while
            if i == tries - 1:
                print(f"  {what} failed ({str(e)[:120]})")
                return False
            time.sleep(15)


def backfill():
    import pipeline
    cfg = json.load(open(os.path.join(HERE, "config.json")))
    yt = data_api(creds())
    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    rng = random.Random()
    in_list = {}  # playlist id -> set of video ids already in it
    added = commented = 0
    for r in posts():
        vid, style = r["video_id"], pipeline.style_of(r)
        title = cfg["youtube"].get("playlists", {}).get(style)
        if title:
            pid = youtube._playlist_id(yt, title)
            if pid not in in_list:
                have, req = set(), yt.playlistItems().list(part="contentDetails", playlistId=pid, maxResults=50)
                try:
                    while req is not None:
                        resp = req.execute()
                        have |= {it["contentDetails"]["videoId"] for it in resp.get("items", [])}
                        req = yt.playlistItems().list_next(req, resp)
                except Exception as e:  # a just-created playlist can 404 for a minute: treat it as empty
                    print(f"  playlist '{title}' not readable yet ({str(e)[:80]}), assuming empty")
                in_list[pid] = have
            if vid not in in_list[pid]:
                if retry(lambda: yt.playlistItems().insert(part="snippet", body={"snippet": {
                        "playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute(),
                        f"{vid}: playlist add"):
                    in_list[pid].add(vid)
                    added += 1
                    print(f"  {vid}: added to '{title}'")
        if cfg["youtube"].get("comments"):
            try:
                threads = yt.commentThreads().list(part="snippet", videoId=vid, maxResults=100).execute()
            except Exception as e:  # comments disabled on the video, etc.
                print(f"  {vid}: can't read comments ({str(e)[:120]})")
                continue
            mine = any(t["snippet"]["topLevelComment"]["snippet"].get("authorChannelId", {}).get("value") == me
                       for t in threads.get("items", []))
            if not mine:
                text = comment_for(r, rng)
                if retry(lambda: yt.commentThreads().insert(part="snippet", body={"snippet": {
                        "videoId": vid, "topLevelComment": {"snippet": {"textOriginal": text}}}}).execute(),
                        f"{vid}: comment"):
                    commented += 1
                    print(f"  {vid}: commented '{text}'")
    summary(f"## Backfill\n- added {added} videos to playlists\n- posted {commented} channel comments")


# ---------------------------------------------------------------- report
METRICS = ["views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage", "likes", "comments",
           "shares", "subscribersGained", "subscribersLost"]


def report(days):
    from googleapiclient.discovery import build
    c = creds()
    yt, ya = data_api(c), build("youtubeAnalytics", "v2", credentials=c, cache_discovery=False)
    rows = posts()
    end = dt.date.today()
    start = min(dt.date.fromisoformat(r["time_utc"][:10]) for r in rows) if days <= 0 else end - dt.timedelta(days=days)
    stats = {}
    ids = [r["video_id"] for r in rows]
    for i in range(0, len(ids), 50):  # live counts (Analytics lags ~2 days)
        for it in yt.videos().list(part="statistics", id=",".join(ids[i:i + 50])).execute().get("items", []):
            stats[it["id"]] = it["statistics"]
    ana = {}
    for i in range(0, len(ids), 200):
        resp = ya.reports().query(ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
                                  metrics=",".join(METRICS), dimensions="video",
                                  filters="video==" + ",".join(ids[i:i + 200]), maxResults=200).execute()
        cols = [h["name"] for h in resp.get("columnHeaders", [])]
        for vals in resp.get("rows", []):
            d = dict(zip(cols, vals))
            ana[d["video"]] = d
    ch = ya.reports().query(ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
                            metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost").execute()
    tot = dict(zip([h["name"] for h in ch["columnHeaders"]], (ch.get("rows") or [[0, 0, 0, 0]])[0]))

    import pipeline
    out = []
    for r in rows:
        a, s = ana.get(r["video_id"], {}), stats.get(r["video_id"], {})
        out.append(dict(time_utc=r["time_utc"], video_id=r["video_id"], style=pipeline.style_of(r), hook=r["hook"],
                        hashtags=r["hashtags"], pattern=r["pattern"], obstacle=r["obstacle"], palette=r["palette"], length_s=r["duration_s"],
                        outcome=r["outcome"], views_now=int(s.get("viewCount", 0)), likes_now=int(s.get("likeCount", 0)),
                        comments_now=int(s.get("commentCount", 0)),
                        **{m: a.get(m, "") for m in METRICS}))
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, f"{end.isoformat()}.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    def avg(group, key):
        v = [float(x[key]) for x in group if x[key] not in ("", None)]
        return sum(v) / len(v) if v else 0

    lines = [f"## YouTube report {start} → {end}",
             f"Channel: **{tot.get('views', 0)} views**, {round(tot.get('estimatedMinutesWatched', 0) / 60, 1)} watch hours, "
             f"+{tot.get('subscribersGained', 0)} / -{tot.get('subscribersLost', 0)} subscribers\n",
             "| style | videos | avg views | avg view (s) | avg % watched | likes/video |", "|---|---|---|---|---|---|"]
    for style in sorted({x["style"] for x in out}):
        g = [x for x in out if x["style"] == style]
        lines.append(f"| {style} | {len(g)} | {avg(g, 'views_now'):.0f} | {avg(g, 'averageViewDuration'):.1f} | "
                     f"{avg(g, 'averageViewPercentage'):.0f}% | {avg(g, 'likes_now'):.1f} |")
    shorts = [x for x in out if x["style"] != "episode"]
    for label, key, vals in (("hashtags (X A/B)", "hashtags", ("yes", "no")),):
        lines.append(f"\n**{label}:** " + ", ".join(
            f"{v}: {avg([x for x in shorts if x[key] == v], 'views_now'):.0f} avg views "
            f"({len([x for x in shorts if x[key] == v])} videos)" for v in vals))
    th = [x for x in shorts if pipeline.is_time_hook(x["hook"])]
    oth = [x for x in shorts if not pipeline.is_time_hook(x["hook"])]
    lines.append(f"\n**\"guess the time\" titles (A/B):** time: {avg(th, 'views_now'):.0f} avg views, "
                 f"{avg(th, 'comments_now'):.1f} comments/video ({len(th)} videos) | others: "
                 f"{avg(oth, 'views_now'):.0f} avg views, {avg(oth, 'comments_now'):.1f} comments/video ({len(oth)} videos)")
    lines += ["\n**Top 5 by views**", "| when | style | hook | views | avg view (s) |", "|---|---|---|---|---|"]
    for x in sorted(out, key=lambda x: -x["views_now"])[:5]:
        lines.append(f"| {x['time_utc']} | {x['style']} | {x['hook']} | {x['views_now']} | {x['averageViewDuration']} |")
    summary("\n".join(lines))
    print(f"wrote {path}")


def export():
    """Dashboard files in data/analytics/dashboard/: videos.csv (per video), daily.csv (channel per day),
    sources.csv (where views come from), channel.csv (live totals). Analytics numbers lag ~2 days."""
    from googleapiclient.discovery import build
    import pipeline
    c = creds()
    yt, ya = data_api(c), build("youtubeAnalytics", "v2", credentials=c, cache_discovery=False)
    rows = posts()
    end = dt.date.today()
    start = min(dt.date.fromisoformat(r["time_utc"][:10]) for r in rows)
    out_dir = os.path.join(OUTDIR, "dashboard")
    os.makedirs(out_dir, exist_ok=True)

    def q(**kw):
        resp = ya.reports().query(ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(), **kw).execute()
        cols = [h["name"] for h in resp.get("columnHeaders", [])]
        return [dict(zip(cols, v)) for v in resp.get("rows", [])]

    def write(name, recs, fields):
        with open(os.path.join(out_dir, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(recs)

    ids = [r["video_id"] for r in rows]
    live = {}
    for i in range(0, len(ids), 50):
        for it in yt.videos().list(part="statistics", id=",".join(ids[i:i + 50])).execute().get("items", []):
            live[it["id"]] = it["statistics"]
    ana = {}
    for i in range(0, len(ids), 200):
        for d in q(metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,shares,"
                           "subscribersGained,subscribersLost", dimensions="video",
                   filters="video==" + ",".join(ids[i:i + 200]), maxResults=200):
            ana[d["video"]] = d
    vids = []
    for r in rows:
        if r["video_id"] not in live:   # deleted videos
            continue
        a, s_ = ana.get(r["video_id"], {}), live[r["video_id"]]
        views, likes = int(s_.get("viewCount", 0)), int(s_.get("likeCount", 0))
        vids.append(dict(posted_utc=r["time_utc"], posted=r["time_utc"][:10], video_id=r["video_id"],
                         style=pipeline.style_of(r), title=r["hook"], length_s=r["duration_s"], views=views, likes=likes,
                         likes_per_1k=round(likes / views * 1000, 1) if views else "",
                         watch_min=round(a["estimatedMinutesWatched"], 1) if a else "",
                         avg_view_s=round(a["averageViewDuration"], 1) if a else "",
                         pct_watched=round(a["averageViewPercentage"], 1) if a else "",
                         shares=a.get("shares", "") if a else "", subs_gained=a.get("subscribersGained", "") if a else "",
                         subs_lost=a.get("subscribersLost", "") if a else ""))
    write("videos.csv", vids, list(vids[0]))
    daily = q(metrics="views,estimatedMinutesWatched,averageViewDuration,likes,shares,subscribersGained,subscribersLost",
              dimensions="day", sort="day")
    for d in daily:
        d["watch_hours"] = round(d["estimatedMinutesWatched"] / 60, 2)
    write("daily.csv", daily, ["day", "views", "watch_hours", "averageViewDuration", "likes", "shares",
                               "subscribersGained", "subscribersLost"])
    src = q(metrics="views,estimatedMinutesWatched", dimensions="insightTrafficSourceType", sort="-views")
    names = {"SHORTS": "Shorts feed", "YT_SEARCH": "YouTube search", "SUBSCRIBER": "Subscriptions / home",
             "YT_CHANNEL": "Your channel page", "YT_OTHER_PAGE": "Other YouTube pages", "RELATED_VIDEO": "Suggested videos",
             "EXT_URL": "Outside websites", "NO_LINK_OTHER": "Direct / unknown", "PLAYLIST": "Playlists",
             "NOTIFICATION": "Notifications", "HASHTAGS": "Hashtag pages", "SOUND_PAGE": "Sound pages",
             "YT_PLAYLIST_PAGE": "Playlist pages", "END_SCREEN": "End screens", "ANNOTATION": "Cards"}
    for d in src:
        d["source"] = names.get(d["insightTrafficSourceType"], d["insightTrafficSourceType"].replace("_", " ").title())
        d["watch_hours"] = round(d["estimatedMinutesWatched"] / 60, 2)
    write("sources.csv", src, ["source", "views", "watch_hours"])
    ch = yt.channels().list(part="statistics", mine=True).execute()["items"][0]["statistics"]
    write("channel.csv", [dict(as_of=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                               subscribers=ch.get("subscriberCount"), channel_views=sum(v["views"] for v in vids),
                               videos=len(vids))], ["as_of", "subscribers", "channel_views", "videos"])
    summary(f"## Dashboard export\n- {len(vids)} videos, {len(daily)} days, {len(src)} traffic sources -> {out_dir}")


def relax_seo():
    """Give already-posted relax videos the search-friendly title, opening line and tags (relax.py SEO, 2026-11-26)."""
    import relax
    yt = data_api(creds())
    for r in posts():
        if r.get("pattern") != "relax":
            continue
        it = yt.videos().list(part="snippet", id=r["video_id"]).execute().get("items", [])
        if not it:
            continue
        sn = it[0]["snippet"]
        label = relax.length_label(float(r.get("duration_s") or 3600))
        intro = relax.seo_intro(label)
        title = relax.TITLES[0].format(len=label)[:100]
        desc = sn.get("description", "")
        if intro not in desc:
            desc = intro + "\n\n" + desc
        tags = list(dict.fromkeys((sn.get("tags") or []) + relax.SEO_TAGS))
        body = {"id": r["video_id"], "snippet": {"title": title, "description": desc[:5000], "tags": tags,
                                                 "categoryId": sn.get("categoryId", "24")}}
        yt.videos().update(part="snippet", body=body).execute()
        summary(f"- {r['video_id']}: '{sn['title']}' -> '{title}'")


def delete_video(vid):
    """Delete one of the channel's videos (only when Trevor asks) and drop its row from data/posts.csv."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or ""):
        sys.exit("give --video with an 11-character YouTube video id")
    data_api(creds()).videos().delete(id=vid).execute()
    with open(POSTS, newline="") as f:
        rd = csv.DictReader(f)
        fields, rows = rd.fieldnames, list(rd)
    keep = [r for r in rows if video_id(r.get("youtube_url")) != vid]
    with open(POSTS, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(keep)
    summary(f"## Deleted\n- https://youtube.com/watch?v={vid} deleted; {len(rows) - len(keep)} row(s) removed from posts.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["check", "backfill", "report", "votes", "delete", "export", "relax-seo"])
    ap.add_argument("--video", default="", help="delete: the YouTube video id to delete (also removed from posts.csv)")
    ap.add_argument("--days", type=int, default=0, help="report window in days (0 = since the first post)")
    a = ap.parse_args()
    if a.action == "relax-seo":
        return relax_seo()
    if a.action == "export":
        return export()
    if a.action == "delete":
        return delete_video(a.video.strip())
    if a.action == "votes":
        import votes
        return votes.debug()
    {"check": check, "backfill": backfill, "report": lambda: report(a.days)}[a.action]()


if __name__ == "__main__":
    main()
