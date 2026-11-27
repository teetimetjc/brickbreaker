#!/usr/bin/env python3
"""
BRICK PICKS runner: makes a sports pick (before the game) or result (after it) video with picks.py, writes captions,
keeps the prediction record in data/picks.csv, and posts (YouTube / X / TikTok drafts) when --live.

  python3 sports.py --mode pick   --away CHIEFS --home BILLS --banner "THANKSGIVING · WHO DO THE BRICKS PICK?"
  python3 sports.py --mode result --away CHIEFS --home BILLS --winner BILLS --score 27-24 --live

Team names as text + colors only (no logos). No betting framing anywhere.
"""
import argparse
import csv
import datetime as dt
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import picks  # noqa: E402

RECORD = os.path.join(HERE, "data", "picks.csv")
FIELDS = ["time_utc", "mode", "league", "away", "home", "pick", "winner", "score", "correct", "url"]

# primary color, alternate (used when the two teams' colors are too close). Text/colors only - never logos.
NFL = {
    "CARDINALS": ("97233f", "ffb612"), "FALCONS": ("a71930", "a5acaf"), "RAVENS": ("6a3fc8", "9e7c0c"),
    "BILLS": ("00338d", "c60c30"), "PANTHERS": ("0085ca", "bfc0bf"), "BEARS": ("c83803", "0b162a"),
    "BENGALS": ("fb4f14", "ffffff"), "BROWNS": ("ff3c00", "8b5a2b"), "COWBOYS": ("003594", "869397"),
    "BRONCOS": ("fb4f14", "002244"), "LIONS": ("0076b6", "b0b7bc"), "PACKERS": ("2e6b4f", "ffb612"),
    "TEXANS": ("a71930", "03202f"), "COLTS": ("002c5f", "a2aaad"), "JAGUARS": ("006778", "d7a22a"),
    "CHIEFS": ("e31837", "ffb81c"), "RAIDERS": ("a5acaf", "ffffff"), "CHARGERS": ("0080c6", "ffc20e"),
    "RAMS": ("003594", "ffa300"), "DOLPHINS": ("008e97", "fc4c02"), "VIKINGS": ("4f2683", "ffc62f"),
    "PATRIOTS": ("002244", "c60c30"), "SAINTS": ("d3bc8d", "ffffff"), "GIANTS": ("0b2265", "a71930"),
    "JETS": ("125740", "ffffff"), "EAGLES": ("2e9e6f", "a5acaf"), "STEELERS": ("ffb612", "ffffff"),
    "49ERS": ("aa0000", "b3995d"), "SEAHAWKS": ("69be28", "002244"), "BUCCANEERS": ("d50a0a", "ff7900"),
    "TITANS": ("4b92db", "c8102e"), "COMMANDERS": ("8a1c1c", "ffb612"),
}


def rgb(hx):
    hx = hx.lstrip("#")
    return tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))


def team_colors(a, b, override=None):
    """Bright, distinguishable colors for the two teams (alternate color if they'd look the same)."""
    override = override or {}
    ca = picks.lift(rgb(override.get(a) or NFL.get(a, ("e0e0e0", "ffffff"))[0]))
    cb = picks.lift(rgb(override.get(b) or NFL.get(b, ("e0e0e0", "ffffff"))[0]))
    if sum((x - y) ** 2 for x, y in zip(ca, cb)) ** 0.5 < 110 and b in NFL and not override.get(b):
        cb = picks.lift(rgb(NFL[b][1]))
    return ca, cb


def load_record():
    if not os.path.exists(RECORD):
        return []
    with open(RECORD, newline="") as f:
        return list(csv.DictReader(f))


def tally(rows):
    w = sum(1 for r in rows if r["mode"] == "result" and r["correct"] == "yes")
    l = sum(1 for r in rows if r["mode"] == "result" and r["correct"] == "no")
    return w, l


def last_pick(rows, away, home):
    for r in reversed(rows):
        if r["mode"] == "pick" and {r["away"], r["home"]} == {away, home}:
            return r["pick"]
    return None


def captions(mode, away, home, team, score, correct, rec, cfg, league):
    a, h, t = away.title(), home.title(), team.title()
    tag = "#" + league.lower()
    if mode == "pick":
        hook = random.choice([f"The bricks have made their pick: {a} or {h}? 🏈",
                              f"{a} vs {h}: who do the bricks pick? 🏈",
                              f"One football decides {a} vs {h} 🏈"])
        x = f"{hook}\n\nWho you got? 👇"
        desc = (f"{a} vs {h}. One football drops through the bricks and lands on the bricks' pick. "
                "Comment who you've got! Just for fun, not betting advice.")
        comment = f"{a} or {h}? Drop your pick 👇 We'll post the result after the game."
    else:
        w, l = rec
        verdict = "called it ✅" if correct == "yes" else "missed this one ❌" if correct == "no" else "are watching 👀"
        hook = f"{t} win{' ' + score if score else ''}! The bricks {verdict}"
        x = f"{hook}\nBrick Picks record: {w}-{l} 🏈"
        desc = f"Final: {t} win {score}. Brick Picks record this season: {w}-{l}."
        comment = "Who should the bricks pick next? 👇"
    tags = ["#brickpicks", tag, "#satisfying"]
    yt = {"title": f"{hook} {tags[0]}"[:100], "description": "\n".join([hook, "", desc, "", " ".join(tags)]),
          "tags": cfg["youtube"]["tags"] + [league, away.lower(), home.lower(), "brick picks"],
          "playlist": cfg["youtube"].get("playlists", {}).get("pick", "Brick Picks"), "comment": comment}
    return {"youtube": yt, "x": {"text": x, "hook": hook, "hashtags": False},
            "tiktok": {"text": f"{hook} {'Who you got? 👇' if mode == 'pick' else 'Which game should the bricks pick next? 👇'} #brickpicks {tag} #satisfying"}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["pick", "result"], default="pick")
    ap.add_argument("--away", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--winner", default="", help="result mode: the team that actually won")
    ap.add_argument("--score", default="", help="result mode, e.g. 27-24")
    ap.add_argument("--banner", default="")
    ap.add_argument("--league", default="NFL")
    ap.add_argument("--colors", default="", help="override, e.g. CHIEFS:e31837,BILLS:00338d")
    ap.add_argument("--platforms", default="youtube,x,tiktok")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--out", default=os.path.join(HERE, "output", "picks"))
    a = ap.parse_args()
    away, home = a.away.strip().upper(), a.home.strip().upper()
    live = a.live or os.environ.get("AUTOPOST_LIVE", "").lower() in ("1", "true", "yes")
    cfg = json.load(open(os.path.join(HERE, "config.json")))
    override = {k.strip().upper(): v for k, _, v in (p.partition(":") for p in a.colors.split(",") if ":" in p)}
    ca, cb = team_colors(away, home, override)
    rows = load_record()
    winner = a.winner.strip().upper() or None
    if a.mode == "result" and winner not in (away, home):
        sys.exit("result mode needs --winner set to one of the two teams")
    prior = last_pick(rows, away, home)
    correct = "" if a.mode == "pick" or not prior else ("yes" if prior == winner else "no")
    rec = tally(rows + ([{"mode": "result", "correct": correct}] if correct else []))
    if a.mode == "pick":
        banner = a.banner or "WHO DO THE BRICKS PICK?"
        extras = {"subscribe": "FOLLOW FOR BRICK PICKS", "subline": "Who you got?"}
    else:
        banner = a.banner or (f"FINAL · {a.score}" if a.score else "FINAL")
        sub = "The bricks called it!" if correct == "yes" else "The bricks missed this one" if correct == "no" else ""
        extras = {"subscribe": f"BRICK PICKS RECORD {rec[0]}-{rec[1]}", "headline": "{winner} WIN" +
                  (f" {a.score}" if a.score else ""), "subline": sub or "Final"}
    os.makedirs(a.out, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(a.out, f"{a.mode}_{away}_{home}_{stamp}.mp4")
    meta = picks.make_pick(dict(teams=[(away, ca), (home, cb)], seed=random.randint(1, 10 ** 6), winner=winner,
                                banner=banner, card_extras=extras), path)
    team = meta["winner"]
    caps = captions(a.mode, away, home, team, a.score, correct, rec, cfg, a.league)
    lines = [f"## Brick Picks ({a.mode}, {'LIVE' if live else 'DRY RUN'})", f"{away} vs {home}: bricks show **{team}**",
             f"YouTube title: {caps['youtube']['title']}", f"X: {caps['x']['text']}",
             f"TikTok caption: {caps['tiktok']['text']}"]
    urls = {}
    if live:
        from publishers import tiktok, x, youtube
        pubs = {"youtube": youtube, "x": x, "tiktok": tiktok}
        for name in [p.strip() for p in a.platforms.split(",") if p.strip() in pubs]:
            if not pubs[name].configured():
                lines.append(f"{name}: skipped (no keys)")
                continue
            try:
                urls[name] = pubs[name].post(path, caps[name], cfg.get(name, {}))
                lines.append(f"{name}: {urls[name]}")
            except Exception as e:  # one platform failing doesn't stop the others
                lines.append(f"{name}: ERROR {e}")
        new = not os.path.exists(RECORD)
        with open(RECORD, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow(dict(time_utc=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), mode=a.mode,
                            league=a.league, away=away, home=home, pick=team if a.mode == "pick" else prior or "",
                            winner=winner or "", score=a.score, correct=correct,
                            url=urls.get("youtube") or urls.get("x") or ""))
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
