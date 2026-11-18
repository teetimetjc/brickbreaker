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
- `pipeline.py` – `--platforms all|x|youtube` limits where to post. Renders N random videos, writes captions (tease the ending, don't spoil it), saves per-video
  JSON + `run_log.json` + GitHub step summary, posts to each platform whose secrets exist.
  DRY RUN by default; `--live` or `AUTOPOST_LIVE=true` posts for real.
  Quote mode: `--quote <X link> [--text "caption"] [--ending win|lose|any] [--word MONDAY]` renders 1 video and
  posts it to X only with `quote_tweet_id`. Word videos force no walls + 20px bricks so letters stay readable.
  The workflow's Run button has matching quote/text/ending/word boxes (passed via env vars, not inlined).
- `config.json` – videos_per_run, length range (30–75 s), game_over_share (0.3), caption hooks, hashtags,
  `x.hashtag_share` (0.5 = A/B test: half of X posts get hashtags, half don't).
- `data/posts.csv` – permanent log of every LIVE post (URL, hook, hashtags yes/no, shape, length, ending...),
  appended by pipeline.py and committed back by the workflow. Use it for the view-count review (~2–3 weeks
  after 2026-11-18): fetch views per post (~$0.005 each) and compare hashtags vs none, hooks, length, ending.
- `publishers/youtube.py` – YouTube Data API v3 resumable upload (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN).
- `publishers/x.py` – X API v2 chunked video upload + POST /2/tweets
  (OAuth 1.0a: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET).
- `scripts/get_youtube_token.py` – one-time OAuth helper that prints the YouTube refresh token.
- `.github/workflows/autopost.yml` – GitHub Actions cron twice daily (~8am & 6pm Central), manual
  "Run workflow" with count/live inputs, videos uploaded as artifacts (14 days). Each run also writes
  `captions.txt` (all captions in one file) for posting by hand. Job timeout 150 min (~40 videos).
- `README.md` – setup + go-live checklist.

## Status
- Generator + pipeline dry run tested end to end (~15–25 s render per video).
- X posting WORKS (first live post 2026-11-18 via the v2 /initialize-/append-/finalize upload; the old
  command=INIT form returned 401). X quote posts not yet tried live. YouTube upload WORKS (first test 2026-11-18, channel @NoBrickLB on
  nobrickleftbehind1@gmail.com; error 'youtubeSignupRequired' meant the account had no channel yet).
- GitHub repo: teetimetjc/brickbreaker (private), `main` branch.
- X account: @NoBrickLB (brand-new account; replaces the earlier idea of repurposing @brickbreakerrrr).
  X API: $5 pay-per-use credit (auto-recharge off), 4 OAuth 1.0a secrets in GitHub and working.
  YouTube: Google Cloud project "Meme Coin" (reused), OAuth client "nobrick-uploader" (Web app, redirect
  developers.google.com/oauthplayground), refresh token from OAuth Playground. Consent screen is still in
  TESTING (Publish needs home page + privacy policy links) -> refresh token EXPIRES ~2026-11-25; until the app is
  published, redo the Playground step weekly and update YT_REFRESH_TOKEN. Uploads likely locked PRIVATE until audit.
  NEXT: small public site (GitHub Pages) with home page + privacy policy -> fill Branding, Publish app, apply
  for the YouTube API audit.

## Next steps
1. ~~Create a GitHub repo and push~~ (done: teetimetjc/brickbreaker).
2. Run the workflow manually in dry-run mode; confirm videos appear as artifacts.
3. X keys done + live tests passed. Schedule ON (repo variable AUTOPOST_LIVE=true set 2026-11-18).
   The first 2 test posts (2026-11-18 ~01:05 and ~01:25 UTC) predate data/posts.csv; both had hashtags.
   Idea for later: daily shortlist of viral posts for Trevor to pick from for quote posts (never auto-quote).
4. ~~Quote-tweet support on X~~ (built; untested against the real API until X keys exist). Semi-automatic only –
   Trevor picks the post. Don't auto-quote random strangers' posts at scale (spam risk).
5. Decide: posting service (Upload-Post / Blotato / Ayrshare, ~$20–30/mo, already audited for
   YouTube/TikTok/Meta) vs direct APIs. If a service, add a publisher for it.
6. Add TikTok and Instagram/Facebook Reels (Reels need 5–90 s).

## Constraints / gotchas
- YouTube: unaudited API projects get uploads locked to PRIVATE – apply for the compliance audit or use an
  audited posting service. Upload quota isn't the issue (100/day).
- YouTube "inauthentic content" policy: avoid mass-produced near-identical uploads. Keep 1–2 posts/day with
  lots of variety (shapes, obstacles, lengths, endings).
- X API is pay-per-use: ~$0.015 per post, ~$0.20 if the post has a link – keep links out. Label the account
  "Automated" in X settings.
- TikTok: unaudited apps can only post privately (audit ~2–6 weeks).
- Instagram: Business/Creator account linked to a Facebook Page + Meta app review; video must be at a public URL.
- Targets under ~30 s force big chunky bricks; 30–75 s looks best.
