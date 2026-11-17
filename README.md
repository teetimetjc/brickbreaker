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

* **Dry run (default):** renders the videos and captions and posts nothing. On GitHub, each run's videos can be
  downloaded from the run page (Actions -> the run -> Artifacts) for 14 days.
* **Live:** set the repo variable `AUTOPOST_LIVE` to `true`. Each platform posts only if its secrets exist, so you
  can turn on X first and YouTube later.
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
- [ ] Set repo variable `AUTOPOST_LIVE=true` so the twice-daily schedule posts for real
- [ ] After a week: check which shapes/lengths/endings get the most views and adjust `config.json`

## Settings worth knowing

* Schedule: edit the two `cron:` lines in the workflow (times are UTC).
* `config.json`: `videos_per_run`, `min_len_sec`/`max_len_sec`, `game_over_share` (0.3 = ~30% end in GAME OVER),
  caption hooks and hashtags.
* Captions tease the ending ("Will it make it?") instead of spoiling it.
* Keep links out of X posts: a post with a URL costs about $0.20 instead of $0.015.
