#!/usr/bin/env python3
"""
YOUTUBE NAME REQUESTS: once a week, collect first names viewers asked for in YouTube comments, spell each one in
bricks (~10 s per name), join up to 4 into one "Breaking YOUR names #N" Short, post it to YouTube, and reply to every
requester's comment so they come back (and subscribe) to see it.

Where requests come from (comments from the last 14 days, viewers only, never the channel itself):
  - replies to the channel's own "Comment your name ..." comment, and top-level comments on videos where the channel
    asked for names: a lone name ("Sarah", "mary ann") or a phrase ("my name is Sarah", "do Sarah")
  - any other comment: only the explicit phrases ("my name is Sarah", "can you do Sarah")
Safety: letters only, 1-2 words of 2-12 letters, no color/common words, a profanity / prank-name blocklist, one name
per person per batch, each comment used once (data/name_requests.csv).

  python3 namereq.py                 # dry run: list candidates, render the Short into output/names/
  python3 namereq.py --list          # only list what would be used
  python3 namereq.py --live          # render, post to YouTube, reply to the requesters, log
"""
import argparse
import csv
import datetime as dt
import os
import random
import re
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import brick_breaker_gen as gen  # noqa: E402
import pipeline  # noqa: E402
import votes  # noqa: E402

LOG = os.path.join(HERE, "data", "name_requests.csv")
LOG_FIELDS = ["time_utc", "name", "comment_id", "thread_id", "author", "video_url"]

ASK_RX = re.compile(r"your (first )?name", re.I)   # the channel's name-request comments contain this
PHRASE = re.compile(r"(?:my name is|my name's|my names|name is|name:|do my name[:,]?|can you do|could you do|"
                    r"please do|pls do|plz do|do mine[:,]?|spell)\s+([A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*)?)",
                    re.I)
NAME_RX = re.compile(r"^[A-Za-z][A-Za-z'\-]{1,11}( [A-Za-z][A-Za-z'\-]{1,11})?$")

COMMON = set("""
a an and the this that these it its is was are be me my mine you your yours we us our he she they them i im
yes no yep nope ok okay lol lmao lmfao rofl omg wow nice cool great good bad best worst love like hate wait what why
how who when where which first second last same more again please pls plz thanks thank ty bro bruh dude man girl guy
sis fam yo hi hey hello bye satisfying satisfy oddly so very too fast slow long short close win won lose lost team
red blue green purple yellow gold mint grape orange pink black white color colour colors ball balls brick bricks
ring rings drop escape battle video short shorts name names do try spell one two three four five go goes going
amazing awesome insane crazy fire lit sick dope wild fun funny boring again rematch next new old real fake
""".split())

# lowercase, spaces/punctuation removed before matching; covers swears, slurs and well-known prank names
BLOCK_SUB = """
fuck fuk fck shit sht bitch btch cunt cock dick pussy puss nigg fag slut whore hoe porn sex rape rapist
nazi hitler kkk penis vagina anus anal cum jizz tits titty boob dildo horny nude naked retard spastic kys killyourself
suicide molest pedo incest bastard twat wank jerkoff blowjob handjob deez ligma sugma bofa joemama yourmom yomama
mikehunt mikeoxlong mikelitoris bendover benderover hughjass hughmungus phatass amandahugginkiss hugginkiss
mccracken seymourbutz seymorebutts heywood jacoff jackoff ivanaticklemee ivana tinydick bigdick smalldick weiner
wiener poop poo fart pee piss butt booty dumbass jackass asshole arse crap damn hell satan isis terrorist
""".split()
BLOCK_WORD = set("ass cum tit gay homo nut nuts ho sus pp".split())


def clean(raw):
    n = unicodedata.normalize("NFKD", raw or "").encode("ascii", "ignore").decode()
    n = re.sub(r"[^A-Za-z' \-]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def acceptable(name):
    if not NAME_RX.match(name):
        return False
    words = [w.strip("'-").lower() for w in name.split()]
    if any(w in COMMON or w in BLOCK_WORD or len(w) < 2 for w in words):
        return False
    flat = re.sub(r"[^a-z]", "", name.lower())
    return not any(b in flat for b in BLOCK_SUB)


def extract(text, lone_ok):
    """The requested name in a comment, or None."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()  # Zoë -> Zoe
    m = PHRASE.search(text)
    if m:
        cand = clean(m.group(1))
        parts = cand.split()
        # keep a second word only if it looks like part of the name (capitalised in the original)
        if len(parts) == 2 and not parts[1][:1].isupper():
            cand = parts[0]
        return cand.title() if acceptable(cand) else None
    if lone_ok:
        cand = clean(text)
        if acceptable(cand):
            return cand.title()
    return None


def used_comment_ids():
    if not os.path.exists(LOG):
        return set()
    with open(LOG, newline="") as f:
        return {r["comment_id"] for r in csv.DictReader(f)}


def collect(yt, max_days=14):
    """[{name, comment_id, thread_id, author, published}] oldest first, deduped."""
    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    vids, _ = votes.window(max_days)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_days)
    used = used_comment_ids()
    found = []
    for vid in vids:
        try:
            threads, req = [], yt.commentThreads().list(part="snippet,replies", videoId=vid, maxResults=100,
                                                        textFormat="plainText")
            while req is not None:
                resp = req.execute()
                threads += resp.get("items", [])
                req = yt.commentThreads().list_next(req, resp)
        except Exception as e:
            print(f"  can't read comments on {vid} ({str(e)[:100]})")
            continue
        asked_here = any(t["snippet"]["topLevelComment"]["snippet"].get("authorChannelId", {}).get("value") == me
                         and ASK_RX.search(t["snippet"]["topLevelComment"]["snippet"].get("textDisplay", ""))
                         for t in threads)
        for t in threads:
            top = t["snippet"]["topLevelComment"]
            ts = top["snippet"]
            ours = ts.get("authorChannelId", {}).get("value") == me
            items = []
            if not ours:
                items.append((top, asked_here))
            replies = t.get("replies", {}).get("comments", [])
            if t["snippet"].get("totalReplyCount", 0) > len(replies):
                replies = yt.comments().list(part="snippet", parentId=t["id"], maxResults=100,
                                             textFormat="plainText").execute().get("items", [])
            ask_thread = ours and bool(ASK_RX.search(ts.get("textDisplay", "")))
            items += [(rp, ask_thread) for rp in replies]
            for c, lone_ok in items:
                s = c["snippet"]
                author = s.get("authorChannelId", {}).get("value")
                if author == me or c["id"] in used or votes._parse(s["publishedAt"]) < cutoff:
                    continue
                name = extract(s.get("textDisplay", ""), lone_ok)
                if name:
                    found.append(dict(name=name, comment_id=c["id"], thread_id=t["id"], author=author,
                                      published=s["publishedAt"], text=s.get("textDisplay", "")[:80]))
    found.sort(key=lambda r: r["published"])
    out, names, authors = [], set(), set()
    for r in found:
        if r["name"].lower() in names or r["author"] in authors:
            continue
        names.add(r["name"].lower())
        authors.add(r["author"])
        out.append(r)
    return out


def render(reqs, outdir, seed):
    """One ~10 s clip per name, joined into a single Short. Returns (path, total bricks)."""
    rng = random.Random(seed)
    clips, bricks = [], 0
    for i, r in enumerate(reqs):
        last = i == len(reqs) - 1
        for attempt in range(6):  # closed floor = always CLEARED; re-roll designs the tuner can't fit in time
            vcfg = gen.random_cfg(rng, gen.default_cfg(max_cell=20), 11, 13, 0)
            vcfg.update(pattern="text", text=pipeline.format_name(r["name"]), obstacle="none", cell=20, balls=None,
                        split_every=0, lose=False, outcome="win", cold_open=False, hp=1,
                        reject_over=None if attempt == 5 else 17)
            vcfg["card_extras"] = {"subscribe": "COMMENT YOUR NAME FOR NEXT WEEK"} if last else None
            clip = os.path.join(outdir, f"name_{i + 1}_{vcfg['seed']}.mp4")
            try:
                meta = gen.make_video(vcfg, clip)
                break
            except gen.TooLong as e:
                print(f"  {r['name']}: {e}; re-rolling")
        bricks += meta["bricks"]
        clips.append(clip)
    out = os.path.join(outdir, f"your_names_{seed}.mp4")
    ins = sum((["-i", c] for c in clips), [])
    filt = "".join(f"[{k}:v][{k}:a]" for k in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=1[v][a]"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-filter_complex", filt, "-map", "[v]", "-map", "[a]",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-b:a", "160k", "-movflags", "+faststart", out])
    if r.returncode:
        raise RuntimeError("ffmpeg concat failed")
    for c in clips:
        os.remove(c)
    return out, bricks


def batch_number():
    path = os.path.join(HERE, "data", "posts.csv")
    if not os.path.exists(path):
        return 1
    with open(path, newline="") as f:
        return 1 + sum(1 for r in csv.DictReader(f) if r.get("pattern") == "names")


def captions(reqs, k, cfg):
    names = [r["name"] for r in reqs]
    listed = ", ".join(names[:-1]) + f" & {names[-1]}" if len(names) > 1 else names[0]
    tags = cfg["youtube"].get("hashtags_by_style", {}).get("names", ["#yourname", "#satisfying", "#brickbreaker"])
    title = f"Breaking YOUR names #{k} 🧱 {listed}"
    if len(title) + len(tags[0]) + 1 <= 100:
        title += " " + tags[0]
    desc = "\n".join([f"Breaking YOUR names #{k}: {listed}.", "",
                      "Want yours next? Comment your first name on any of our videos and it might get broken in "
                      "bricks next week.", "", " ".join(tags)])
    return {"title": title[:100], "description": desc, "tags": cfg["youtube"]["tags"],
            "playlist": cfg["youtube"].get("playlists", {}).get("names"),
            "comment": "Want your name next? Comment it below 👇 (first names only)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--list", action="store_true", help="only list the requests found")
    ap.add_argument("--min", type=int, default=None)
    ap.add_argument("--max", type=int, default=None)
    a = ap.parse_args()
    cfg = pipeline.load_config(os.path.join(HERE, "config.json"))
    nc = cfg.get("name_requests", {})
    lo, hi = a.min or nc.get("min_names", 2), a.max or nc.get("max_names", 4)
    live = a.live or os.environ.get("AUTOPOST_LIVE", "").lower() in ("1", "true", "yes")
    yt = votes._service()
    reqs = collect(yt, nc.get("max_days", 14))
    print(f"{len(reqs)} name request(s) found:")
    for r in reqs:
        print(f"  {r['name']:<14} from comment {r['text']!r}")
    summary = [f"## YouTube name requests ({'LIVE' if live else 'DRY RUN'})",
               f"{len(reqs)} request(s): " + (", ".join(r["name"] for r in reqs) or "none")]
    if a.list:
        return
    if len(reqs) < lo:
        summary.append(f"Fewer than {lo}: waiting for more (they stay queued).")
        print(summary[-1])
        _write_summary(summary)
        return
    reqs = reqs[:hi]
    outdir = os.path.join(HERE, "output", "names")
    os.makedirs(outdir, exist_ok=True)
    seed = random.randint(1, 10 ** 6)
    path, bricks = render(reqs, outdir, seed)
    k = batch_number()
    cap = captions(reqs, k, cfg)
    print(f"title: {cap['title']}")
    summary.append(f"Video: {os.path.basename(path)} | title: {cap['title']}")
    if not live:
        _write_summary(summary)
        return
    from publishers import youtube
    url = youtube.post(path, cap, cfg.get("youtube", {}))
    print(f"posted: {url}")
    summary.append(f"Posted: {url}")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        for r in reqs:
            w.writerow(dict(time_utc=now, name=r["name"], comment_id=r["comment_id"], thread_id=r["thread_id"],
                            author=r["author"], video_url=url))
    for r in reqs:  # reply to each requester (no links: link comments get held as spam)
        msg = random.choice([f"{r['name']}, your name is in our newest Short! 🧱 Find it on the channel",
                             f"Done, {r['name']}! 🧱 Your name just got broken in our latest Short",
                             f"{r['name']}, you're in this week's Breaking YOUR names! 🧱 Check our newest Short"])
        try:
            yt.comments().insert(part="snippet", body={"snippet": {"parentId": r["thread_id"],
                                                                   "textOriginal": msg}}).execute()
            print(f"  replied to {r['name']}")
        except Exception as e:
            print(f"  reply to {r['name']} failed ({str(e)[:120]})")
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                               capture_output=True, text=True).stdout or 0)
    meta = dict(file=path, pattern="names", obstacle="none", palette="names", duration=dur, outcome="win",
                cleared_pct=100, bricks=bricks, start_balls=0, bonus_every=0, peak_balls=0)
    pipeline.append_post_log([{"video": meta, "captions": {"x": {"hook": cap["title"], "hashtags": False}},
                               "posts": {"youtube": {"url": url}}}], "")
    _write_summary(summary)


def _write_summary(lines):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a") as f:
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
