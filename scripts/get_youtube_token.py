#!/usr/bin/env python3
"""
One-time helper: sign in to the YouTube channel and print a refresh token for GitHub secrets.

1. In Google Cloud Console: create a project, enable "YouTube Data API v3",
   set up the OAuth consent screen (External; add yourself as a test user),
   then create an OAuth client ID of type "Desktop app" and download it as client_secret.json.
2. Run on your computer:  pip install google-auth-oauthlib && python3 scripts/get_youtube_token.py client_secret.json
3. A browser opens - pick the brand account/channel you'll post to and allow access.
4. Copy the three printed values into GitHub > Settings > Secrets and variables > Actions.

Note: while the consent screen is in "Testing", Google expires refresh tokens after 7 days.
Publish the consent screen ("In production") so the token keeps working.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

if len(sys.argv) != 2:
    sys.exit("usage: python3 get_youtube_token.py client_secret.json")

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
info = json.load(open(sys.argv[1]))
client = info.get("installed") or info.get("web")
print("\nAdd these as GitHub Actions secrets:\n")
print(f"YT_CLIENT_ID      = {client['client_id']}")
print(f"YT_CLIENT_SECRET  = {client['client_secret']}")
print(f"YT_REFRESH_TOKEN  = {creds.refresh_token}")
