# Project: Last Brick (working name) – auto-generated "oddly satisfying" brick-breaker videos

## Goal
Automated pipeline that generates unique brick-breaker simulation videos (balls bounce around destroying a
grid of bricks) and posts them on a schedule to X and YouTube Shorts, later TikTok + Instagram/Facebook Reels,
to grow views/impressions. Inspiration: @diourrene on X (posts these clips and quote-tweets viral posts with
them, ~500K–22M views).

## What exists
- `brick_breaker_gen.py` – video generator (numpy + Pillow + ffmpeg). Vertical 1080x1920, 30 fps, with sound.
  - Patterns: solid, heart, circle, diamond, pyramid, rings, checker, stripes, text (any word)
  - Obstacles (gray indestructible walls): none, vault (sealed box, one small entrance), pillars, shelves,
    funnel, maze. Unreachable bricks are removed automatically.
  - 7 palettes, brick HP, multi-ball, "+1 ball every N bricks" mode
  - Balls can be LOST through an open red drain; paddle AI fumbles occasionally (near-misses). The last
    ball can only be lost after 75% cleared. `--no-lose` closes the floor.
  - Endings: "CLEARED! in 0:39" or "GAME OVER – N bricks left • 93% cleared", each with its own sound.
  - `--target SECONDS` auto-tunes brick size, ball count/bonus balls and speed by running the deterministic
    sim headlessly, so the video ends near the target. `--outcome win|lose|any`.
  - No on-screen HUD. Vertical videos keep a plain safe margin (11.5% each side, 4% top, 6% bottom) because
    phones (~19.5:9) crop the sides of 9:16 video in full-screen and app buttons cover top/bottom. The hook title is generated for captions/YouTube
    title but not drawn; results (time, bricks left, % cleared) only appear on the end card.
  - `--batch N` randomizes everything; `--preview` saves stills; seeds reproduce runs.
  - `make_video()` returns metadata; `default_cfg()` / `random_cfg()` are shared helpers.
- `battle.py` – COLOR BATTLES: split-screen race, two teams (RED/BLUE/GREEN/PURPLE/GOLD) with identical walls,
  closed floor, same balls+speed; only bounce seeds differ. Tuner runs 12 seeds headlessly and picks the pair
  with the closest finish (0.4–8 s gap) and most lead changes near the target length; winner color random.
  Stereo audio (each team panned to its side), team-colored balls/paddles, names on top, "RED WINS!" card.
  Uses gen.Layout(margins=...), Renderer.ball_color. `python3 battle.py --target 45 --out b.mp4`.
- `escape.py` – BRICK ESCAPE: 4 balls (RED/YELLOW/BLUE/GREEN, colors shuffled per race) rise (LIFT) through
  5–8 brick barriers to a checkered finish; neutral bricks break for all, team bricks only for that color,
  balls bump each other. Tuner simulates ~14 seeds per course/speed and picks a close finish with lead changes
  (lead = highest point reached). Themes: `dark` / `light`; DARK ONLY since 2026-11-23 (Trevor prefers the black
  background; light still available via --theme light). Logged as palette escape-<theme>. Own physics + Painter (not gen.Sim). `python3 escape.py --theme light --out e.mp4`.
- `compilation.py` – WEEKLY LONG-FORM YouTube episode, widescreen 1920x1080, kept under 14:40 (YouTube needs a
  phone-verified channel for >15 min). Fresh rounds (normal/battle/escape, via battle.configure /
  escape.configure(1920,1080), plus rings/drop since 2026-11-22) with "ROUND N" cards + running color leaderboard, outro with final standings,
  chapters in the description, logged to posts.csv as pattern=compilation (episode number = count + 1).
  Workflow `.github/workflows/compilation.yml`: main timer = 2nd cron-job.org job on Sunday mornings (window=auto ->
  `--once-per-week` skips if an episode was posted in the last 6 days); GitHub cron Sun 15:23 UTC is backup. YouTube only.
  First full dry run on GitHub (2026-11-18): 13:38 long, 14 rounds, rendered in ~6.5 min, ~60 MB artifact.
  THUMBNAILS (channel phone-verified 2026-11-22): `thumbnail.py` makes a 1280x720 JPEG (widescreen battle frame
  mid-race + "WHO WINS?"-style headline + matchup in team colors + EPISODE badge); compilation sets it after upload
  (youtube.set_thumbnail, works with the upload scope). Existing video: workflow input thumb_for=VIDEO_ID,EPISODE.
  Episode 1 LIVE 2026-11-22 (https://youtube.com/watch?v=o5oJnkXf3Zw, 14:10, 19 rounds) - started manually by Claude
  because the cron-job.org weekly job never fired (daily job did); Trevor to check that job is saved/enabled.
- `pipeline.py` – `--style auto|normal|battle|escape` (auto mixes: config `battle_share` 0.3, `escape_share`
  0.25, rest normal);
  `--platforms all|x|youtube` limits where to post. Renders N random videos, writes captions (tease the ending, don't spoil it), saves per-video
  JSON + `run_log.json` + GitHub step summary, posts to each platform whose secrets exist.
  DRY RUN by default; `--live` or `AUTOPOST_LIVE=true` posts for real.
  Quote mode: `--quote <X link> [--text "caption"] [--ending win|lose|any] [--word MONDAY]` renders 1 video and
  posts it to X only with `quote_tweet_id`. Word videos force no walls + 20px bricks so letters stay readable.
  The workflow's Run button has matching quote/text/ending/word boxes (passed via env vars, not inlined).
  Word box accepts "WORD@palette" (e.g. NVDA@lime) to force colors; palettes red ocean sunset mint grape gold blue
  lime rainbow. Ticker/brand words: text only, never draw a company logo (trademark).
- End cards (vertical): `gen.draw_card_extras` adds a red "SUBSCRIBE ..." pill (config subscribe_text /
  subscribe_text_race) and, for battles/escapes, SEASON N STANDINGS (season = calendar month, Season 1 = Nov 2026;
  wins counted from posts.csv outcomes "<color> wins/escapes" via pipeline.season_standings). Battle GOLD team
  renamed YELLOW so battles and escapes share one leaderboard. Widescreen episodes don't use extras.
- VARIETY RULES (pipeline.recent_posts / pick_style / vary_battle / vary_normal, from posts.csv): never the same
  style twice in a row (weights from battle_share/escape_share, last style excluded); battles never repeat the
  previous matchup (Red vs Blue ~35% when allowed) and skip shapes from the last 3 battles; normal videos skip
  shapes from the last 3 normals and the last obstacle. Added after 4 Red-vs-Blue battles in a row (2026-11-19).
  One-off override: config force_style {style, since_utc} makes auto posts that style until one is logged after
  since_utc (pipeline.forced_style); used 2026-11-24 for the first Brick Drop.
- NAME REQUESTS (2026-11-21): `--names "Sarah, Mary Ann"` (workflow input `names`) renders one video per viewer name
  spelled in bricks (format_name: ASCII-folded, 2 lines for two words / hyphen / >8 letters; always ends CLEARED;
  no cold open so the whole name shows first) and sends them to TikTok DRAFTS only unless platforms is set, for
  Trevor to attach via TikTok "Reply with video". Captions: "Breaking <Name>'s name brick by brick ...".
  Text pattern now stretches letters up to 2.2x tall to fill the space (readable names/words everywhere).
- Titles/captions: pipeline.py HOOKS + pick_hook() choose ONE hook per video from what actually happened
  (win/lose, start balls, bonus mode, obstacle, real brick count); used for the YouTube title and X text;
  skips hooks used in the last `recent_hooks_to_avoid` posts (from data/posts.csv). Never spoil the ending.
  A/B TEST (2026-11-23): "guess the time / how long" TITLES stay in the hook pools next to non-time ones (a commenter
  said the video length gives it away, but corrections are comments too); pipeline.is_time_hook tags them and the
  weekly report compares views + comments/video. Channel comments never ask about time. Decide at the Dec review.
- MID-VIDEO SUBSCRIBE BANNER (2026-11-22, `banner.py`): red YouTube-style pill with play icon, pops in ~40% into
  every Short (>=5 s in, ends >=1.5 s before the end card) for 2.5 s at 8.5% from the top; ffmpeg overlay after
  rendering (~6-9 s per video). Text from config mid_banner (race styles battle/escape/drop: "SUBSCRIBE & PICK THE
  NEXT COLOR"; normal/rings: "SUBSCRIBE FOR A NEW ONE DAILY"). Not on name videos. Why: avg view 16-26 s, so most
  viewers never see the end card.
- VIEWER COLOR VOTE (2026-11-23, `votes.py`): when a battle comes up, the pipeline reads YouTube comments + replies on
  posts from the last 10 days, published after the last voted battle (posts.csv column `vote`, e.g. PURPLE:3), counts
  color words/emoji (red/blue/green|mint/purple|grape/yellow|gold, 🔴🔵🟢🟣🟡; not ❤), one vote per person per color,
  channel's own comments excluded. Top color plays (vs the runner-up if it had votes, else random); WINNER is
  still physics. Voted battles get a "YOU VOTED <COLOR>" pill for the first 3 s, HOOKS["voted"] titles, a vote line
  in the description and a "you picked X" channel comment. Unvoted battles: description + 50% of channel comments
  say "the most-picked color plays in the next battle". config vote {enabled, min_votes 1, max_days 10}.
  `python3 votes.py` prints the live tally. posts.csv header auto-upgrades when LOG_FIELDS grows.
- YOUTUBE NAME REQUESTS (2026-11-23, `namereq.py`, workflow `yt-names.yml`, Wed 23:17 UTC + manual): ~35% of
  normal/ring channel comments ask "Comment your name..." (pipeline.NAME_ASKS, config name_requests.ask_share; text
  must match namereq.ASK_RX "your (first) name"). Weekly job reads 14 days of comments: lone names count only as
  replies to that ask or on videos where it was asked; "my name is X"/"can you do X" count anywhere. Filters: letters,
  1-2 words, COMMON words, BLOCK_SUB/BLOCK_WORD profanity + prank names (Mike Hunt etc.), one per person, each comment
  once (data/name_requests.csv). Needs >= 2 names (max 3) else waits. Renders ~15 s per name (closed floor, always
  CLEARED, last card "COMMENT YOUR NAME FOR NEXT WEEK"), concat -> "Breaking YOUR names #N 🧱 A, B & C" on YouTube
  only (playlist "Your Names"), replies to each requester (no links), logs posts.csv pattern=names (style "names").
- RELAX VIDEOS (2026-11-23, `relax.py`, workflow `relax.yml` MANUAL ONLY until Trevor approves the sample): 1-hour
  widescreen long-form for YPP watch hours (Shorts watch time doesn't count). 12-15 calm scenes of 3-5 min (closed floor,
  max_px_per_sec 520-680 so the tuner adds balls instead of speed, calm shapes, obstacles none/pillars/shelves),
  gen cfg end_card=False + soft_audio=True (soft low notes + ambient pad), 1.5 s fades, concat. Title from TITLES,
  chapters per scene, thumbnail "1 HOUR / RELAX · STUDY · SLEEP" from 12 s in, playlist "Relax, Study & Sleep",
  posts.csv pattern=relax (excluded from Shorts variety rules). Render ~35 min per hour on GitHub.
  APPROVED + SCHEDULED 2026-11-23 (Trevor: "anything and everything to keep content different and testing"): ONCE weekly
  (Trevor 2026-11-23), Mon ~7:47 pm Chicago (cron 47 1 * * 2); Vol. 1 started by hand Mon 2026-11-23. Vol. 2 posted by the schedule Tue 11-24
  (GitHub ran it ~10 h late; cron collided with the manual Vol. 1; Trevor had it DELETED same day as too soon -
  youtube-tools action=delete video=ID deletes a video + its posts.csv row) -> scheduled runs now use --once-per-week (skip if a
  relax video is in posts.csv within 6 days). A/B per video: length 60/60/180 min, sound both|pad|notes (gen soft_mix),
  logged as palette relax-<sound>; report CSV now has palette for comparing watch time.
- TIKTOK MIDDAY DRAFT (2026-11-24, `tiktok_names.py`, workflow `tiktok-midday.yml`, daily 17:23 UTC ~11:23 am
  Chicago): 3rd TikTok-only draft per day (Trevor: TikTok tolerates more posts). "Random names": 2 popular first
  names from data/popular_names.txt (skip names used in the last 60 days, data/tiktok_names_used.csv), rendered via
  namereq.render (card "COMMENT YOUR NAME"), ~28 s, sent to the TikTok inbox; caption in run summary + artifact
  captions.txt. Never YouTube/X. Plan: 3/day for 1-2 weeks, 4/day if Trevor keeps up and views hold.
- BRICK PICKS (sports, 2026-11-24, `picks.py` + runner `sports.py` + manual workflow `sports.yml` (mode pick|result,
  away, home, winner, score, banner, platforms, live); record in data/picks.csv (result vs last pick = right/wrong,
  W-L on the result card); NFL team color table with alternates; playlist "Brick Picks"). LOOK APPROVED 2026-11-24
  (picks.DEFAULT_STYLE + football + field are the defaults): one ball (or best of 3)
  drops through peg-bricks into 2 team bins; seed probed for a 5-11 s drop that passes near the middle late (near
  miss); `winner` can force a side (result videos). Styles: hp (pop=(1,), crack=(1,1,2)), pw/ph (wide bricks 34x12),
  balls=3; ball="football" (rotating sprite), theme="field" (turf stripes). Trevor's pick so far (2026-11-24): FIELD +
  1 FOOTBALL + SOLID bricks that stay. Wide/low-bounce version REJECTED (ball slid along flat bricks). Current:
  style hp=(9999,), pw=ph=14, round_pegs=True (round contact so every hit deflects), spacing=100, row_gap=85,
  g=650, bounce=1.75 -> real zigzag bounces, ~10 s drop. Bricks flash white on hit (no break). Team names as text + colors only (no
  logos), dark colors auto-brightened (lift). battle.py end card also takes card_extras headline/subline for picks.
  Thanksgiving 2026: Bears@Lions, Eagles@Cowboys, Chiefs@Bills (8:20 pm ET NBC). No betting framing.
- WATCH-TIME TUNING (2026-11-19, after analytics showed ~11 s average view on 35–75 s Shorts): length range now
  20–45 s; COLD OPEN in all styles (gen.cold_open skips the first moments unrecorded until ~3% of bricks are
  broken / 2.5–3 s; escape skips 1 s; events shifted with gen.shift_events, end times are video time); GAME OVER
  only when ≥85% cleared (paddle collapse_at 0.88–0.97). Normal videos reject ~50% of designs at these lengths
  (cheap re-roll before rendering).
- YouTube hashtags (2026-11-20): no #shorts anywhere (auto-detected); config youtube.hashtags_by_style gives 3 per
  style (battle #colorbattle #pickaside #satisfying / escape #marblerace ... / normal #brickbreaker ... / episode
  #satisfying #relaxing #brickbreaker); the first goes at the end of the title, all 3 end the description.
- `config.json` – videos_per_run, length range (20–45 s), game_over_share (0.3), `max_brick_px` (30: no
  chunky bricks), `recent_hooks_to_avoid` (10), hashtags,
  `x.hashtag_share` (0.5 = A/B test: half of X posts get hashtags, half don't).
- `data/posts.csv` – permanent log of every LIVE post (URL, hook, hashtags yes/no, shape, length, ending...),
  appended by pipeline.py and committed back by the workflow. Use it for the view-count review (~2–3 weeks
  after 2026-11-18): fetch views per post (~$0.005 each) and compare hashtags vs none, hooks, length, ending.
- `publishers/youtube.py` – YouTube Data API v3 resumable upload (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN).
- `publishers/x.py` – X API v2 chunked video upload + POST /2/tweets
  (OAuth 1.0a: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET).
- `scripts/get_youtube_token.py` – one-time OAuth helper that prints the YouTube refresh token.
- `publishers/tiktok.py` – TikTok via a SANDBOX app (no review): Content Posting API "upload to inbox" (scope
  video.upload) -> each video lands as a DRAFT in @nobricklb's TikTok inbox; Trevor adds sound + caption (from
  captions.txt) and posts. Secrets TIKTOK_CLIENT_KEY/SECRET (sandbox creds). Tokens live in data/tiktok_token.enc
  (Fernet, key = sha256 of client secret), refreshed automatically and committed by the workflow (git add data/).
  One-time connect: approval link (scripts/tiktok_connect.py --url-for <client_key>) -> code on
  https://teetimetjc.github.io/nobrick/callback.html -> workflow "TikTok connect (one time)" with that code.
  Website URL prefix https://teetimetjc.github.io/nobrick/ verified in TikTok via tiktok<code>.txt in the nobrick repo.
  CONNECTED 2026-11-19 (account NoBrickLB, sandbox client key sbawtpa3whgqbmlm53); first test draft reached the
  inbox (status SEND_TO_USER_INBOX). Every scheduled post now also goes to TikTok drafts.
- POSTING TIMES: cron-job.org (Trevor's account) POSTs workflow_dispatch for autopost.yml every 30 min during
  config.json `post_windows` (morning 07–11, evening 17–21 America/Chicago) with inputs live=true, window=auto.
  `scripts/gate.py` (runs first, after a fresh git pull of posts.csv) posts with prob 1/(knocks left) -> exactly
  one post per window at a uniformly random slot, plus 0–10 min random wait. GitHub's own crons (15:52/01:52 UTC)
  are only a backup through the same gate (GitHub ran schedules 7+ h late / skipped on 2026-11-18). Decided: 2
  posts/day on both X and YouTube, consistent. cron-job.org job "NoBrick autopost" LIVE since 2026-11-19 01:22 UTC
  (crontab 0,30 7-10,17-20 America/Chicago; headers Authorization Bearer <fine-grained PAT: brickbreaker only,
  Actions read+write>, Accept, X-GitHub-Api-Version, Content-Type, User-Agent (required, else 403)). First knock: 204.
- `.github/workflows/autopost.yml` – GitHub Actions (backup crons, see above), manual
  "Run workflow" with count/live inputs, videos uploaded as artifacts (14 days). Each run also writes
  `captions.txt` (all captions in one file) for posting by hand. Job timeout 150 min (~40 videos).
- `README.md` – setup + go-live checklist.

- `prototypes/` (2026-11-22, NOT in the posting rotation yet): musical bricks (brick breaks play Jingle Bells,
  public domain), glass sound/look edition, sand bricks (breaks crumble into a sand pile), ring escape (ball
  escapes 7 rotating brick rings), BRICK DROP (`drop.py`: peg-drop board whose pegs are bricks with 6 hit points,
  80 balls into 4 color bins, seeds probed headlessly for a close finish; never call it "Plinko" - trademark).
  Trevor LIKES ring escape + brick drop (2026-11-22) -> now integrated as rings.py / brickdrop.py (below).
- `rings.py` – RING ESCAPE style (`rings`): 7–9 spinning brick rings with gaps, ball with gravity; seed probed so the
  escape lands at 12–30 s (own range, ignores longer targets). End card ESCAPED! + subscribe pill (no standings).
- `brickdrop.py` – BRICK DROP style (`drop`): 40–160 balls into 4 color bins through peg-bricks (hp scales with ball
  count), seed probed for a 1-ball-margin finish with lead changes; winner counts toward season standings.
  Shared helpers in `sfx.py`. Mix (config): battle .2, escape .2, rings .15, drop .15, normal rest. Pipeline falls
  back to a normal video if a style can't fit after 5 re-rolls. Weekly episode now includes rings + drop rounds
  too (rings.configure / brickdrop.configure(1920,1080); end cards sized from a phone-width base).

## Status
- Generator + pipeline dry run tested end to end (~15–25 s render per video).
- X posting WORKS (first live post 2026-11-18 via the v2 /initialize-/append-/finalize upload; the old
  command=INIT form returned 401). X quote posts not yet tried live. YouTube upload WORKS (first test 2026-11-18, channel @NoBrickLB on
  nobrickleftbehind1@gmail.com; error 'youtubeSignupRequired' meant the account had no channel yet).
- GitHub repo: teetimetjc/brickbreaker (private), `main` branch.
- X account: @NoBrickLB (brand-new account; replaces the earlier idea of repurposing @brickbreakerrrr).
  X API: $5 pay-per-use credit (auto-recharge off), 4 OAuth 1.0a secrets in GitHub and working.
  YouTube: Google Cloud project "Meme Coin" (reused), OAuth client "nobrick-uploader" (Web app, redirect
  developers.google.com/oauthplayground). Consent screen PUBLISHED (In production) 2026-11-18 with Branding
  links to the website, so the refresh token (re-made after publishing, from OAuth Playground) no longer expires
  weekly. First API upload came out PUBLIC, so no YouTube audit applied for yet; apply only if uploads start
  showing Private (the website covers the audit's privacy-policy requirement).
  Website: public repo teetimetjc/nobrick (index/privacy/terms + .nojekyll, GitHub Pages from main root) ->
  https://teetimetjc.github.io/nobrick/ (contact = X DMs, no email on the page).
  This session can't enable Pages or set repo variables (proxy blocks those GitHub API paths).

## Next steps
1. ~~Create a GitHub repo and push~~ (done: teetimetjc/brickbreaker).
2. Run the workflow manually in dry-run mode; confirm videos appear as artifacts.
3. X keys done + live tests passed. Schedule ON (repo variable AUTOPOST_LIVE=true set 2026-11-18).
   The first 2 test posts (2026-11-18 ~01:05 and ~01:25 UTC) predate data/posts.csv; both had hashtags.
   Idea for later: daily shortlist of viral posts for Trevor to pick from for quote posts (never auto-quote).
4. Quote-tweet support on X: BLOCKED BY X API (tried live 2026-11-24): 403 "You can only reply to or quote posts
   where you are mentioned or are the author." Quote mode can't quote strangers' posts; Trevor quotes by hand in the
   X app with a video Claude renders locally (word@palette) and sends him. Semi-automatic only –
   Trevor picks the post. Don't auto-quote random strangers' posts at scale (spam risk).
5. Decide: posting service (Upload-Post / Blotato / Ayrshare, ~$20–30/mo, already audited for
   YouTube/TikTok/Meta) vs direct APIs. If a service, add a publisher for it.
6. ~~TikTok~~ DONE 2026-11-19 via sandbox drafts (see publishers/tiktok.py); Trevor posts each draft in the app.
   Full auto would need the production app review (demo video of a posting UI). Trevor WANTS this eventually
   (2026-11-21): plan = build a TikTok-guideline posting page on the website + script for his screen recording,
   submit Production with video.publish/Direct Post; fallback = paid audited posting service (~$20–30/mo).
   Instagram/Facebook Reels: SKIPPED for now by Trevor (2026-11-19) - don't push it; revisit only if he asks.
   YouTube token re-made 2026-11-22 with youtube.upload + youtube.force-ssl + yt-analytics.readonly: playlists +
   channel comments now work on every upload (all 13 earlier uploads backfilled).
- `scripts/yt_tools.py` + workflow `youtube-tools.yml` (action check|backfill|report): scope check, playlist/comment
  backfill, and the ANALYTICS REPORT (per-video views/likes now + Analytics API watch time, avg view duration,
  % watched, subs gained; joined with posts.csv; by style + hashtags A/B + top 5) -> data/analytics/<date>.csv
  and the run summary. Runs every Monday 14:41 UTC automatically.

## Constraints / gotchas
- SAFE POSTING CEILING (Trevor 2026-11-23: "as many as won't get us throttled or shut down"): 2 Shorts/day + names
  Short weekly + episode weekly + relax 1x/week (Trevor's choice). Raise Shorts to 3/day only after the Dec review if retention holds.
  Never more than 2 relax/week (they look the most alike -> YPP "repetitious/inauthentic content" rejection risk).
- YouTube: unaudited API projects CAN get uploads locked to PRIVATE (not seen so far) – if it happens, apply for
  the compliance audit or use an audited posting service. Upload quota isn't the issue (100/day).
- YouTube "inauthentic content" policy: avoid mass-produced near-identical uploads. Keep 1–2 posts/day with
  lots of variety (shapes, obstacles, lengths, endings).
- X API is pay-per-use: ~$0.015 per post, ~$0.20 if the post has a link – keep links out.
  NO X analytics reads (Trevor 2026-11-23: don't spend credit on it; he checks the 📊 on posts himself). Label the account
  "Automated" in X settings.
- TikTok: unaudited apps can only post privately (audit ~2–6 weeks).
- Instagram: Business/Creator account linked to a Facebook Page + Meta app review; video must be at a public URL.
- Bricks are capped at 30 px (max_brick_px). The tuner raises gen.TooLong before rendering when cfg['reject_over']
  is set and the predicted length is too long; pipeline re-rolls up to 8 designs (cheap, no render).
