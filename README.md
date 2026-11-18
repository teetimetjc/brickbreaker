# Brick Breaker Autopost

Makes "oddly satisfying" brick-breaker videos (vertical 1080x1920, with sound) and posts them on a schedule.

```
brick_breaker_gen.py        the video generator (works on its own too: --help)
pipeline.py                 render N random videos -> captions -> post to each platform that has keys
config.json                 videos per run, length range, game-over share, captions, hashtags
publishers/youtube.py       YouTube Data API uploader
publishers/x.py             X API v2 video poster
scripts/get_youtube_token.py  one-time helper to get the YouTube refresh token
.github/workflows/autopost.yml  runs twice a day on GitHub Actions
```

## How it runs

* **Scheduled runs post for real** (twice a day) to every platform whose secrets exist, so X can be on while
  YouTube isn't set up yet. **To pause posting:** set the repo variable `AUTOPOST_LIVE` to `false`
  (Settings -> Secrets and variables -> Actions -> Variables), or disable the workflow on the Actions tab.
* **Manual runs** (Run workflow button) are dry runs unless you set live = `true`. Each run's videos can be
  downloaded from the run page (Actions -> the run -> Artifacts) for 14 days.
* Every live post is logged in `data/posts.csv` (kept permanently) for comparing views later.
* A failed post on one platform doesn't stop the other. The run is marked failed so you get GitHub's email.

Local test: `pip install -r requirements.txt` (plus ffmpeg), then `python3 pipeline.py --count 2`.

## Go-live checklist

**Accounts**
- [ ] Create the YouTube channel (a Brand Account is best, so it isn't tied to your personal name)
- [ ] Create the X account; add the "Automated" label in settings (Account -> Automation) and link your personal account as the manager
- [ ] Pick the name/handle and profile art used on both

**GitHub**
- [ ] Create a private repo and push this folder
- [ ] Actions -> "Brick breaker autopost" -> Run workflow (live = false) and check the videos it produced

**X**
- [ ] developer.x.com: sign up with the new account, create a Project + App
- [ ] App permissions: "Read and write"; generate API Key/Secret and Access Token/Secret
- [ ] Add pay-per-use credits (about $5 covers a month of 2 posts/day)
- [ ] Add secrets `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`

**YouTube**
- [ ] Google Cloud Console: new project, enable "YouTube Data API v3"
- [ ] OAuth consent screen (External), publish it "In production" so tokens don't expire after 7 days
- [ ] Create OAuth client (Desktop app), download `client_secret.json`
- [ ] Run `python3 scripts/get_youtube_token.py client_secret.json`, sign in as the channel
- [ ] Add secrets `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`
- [ ] Apply for the YouTube API compliance audit (until it passes, API uploads may be locked to private)

**Go live**
- [ ] Run workflow manually with live = true, count = 1; check both posts
- [x] Twice-daily schedule posts for real (pause with repo variable `AUTOPOST_LIVE=false`)
- [ ] After a week: check which shapes/lengths/endings get the most views and adjust `config.json`

## Quote-posting a viral post on X

You pick the post; the pipeline renders a fresh video and posts it on X as a quote of that post.

1. On GitHub: **Actions → Brick breaker autopost → Run workflow**.
2. **quote**: paste the post's link (Share → Copy link in the X app).
3. **text**: your caption – the joke that ties the post to the video. Blank = a random hook.
4. **ending**: `lose` (GAME OVER) or `win` (CLEARED!) to fit the joke, or `any`.
5. **word** (optional): spell a word in bricks, e.g. `MONDAY`.
6. **live**: `false` first to check the video in the run's artifacts, `true` to post.

Quote runs post to X only (not YouTube) and make one video. From the command line:
`python3 pipeline.py --quote <link> --text "..." --ending lose --word MONDAY [--live]`

Only quote posts where the video actually fits. Mass-quoting random viral posts gets accounts limited.

## Settings worth knowing

* Schedule: edit the two `cron:` lines in the workflow (times are UTC).
* `config.json`: `videos_per_run`, `min_len_sec`/`max_len_sec`, `game_over_share` (0.3 = ~30% end in GAME OVER),
  caption hooks and hashtags.
* Captions tease the ending ("Will it make it?") instead of spoiling it.
* Keep links out of X posts: a post with a URL costs about $0.20 instead of $0.015.
