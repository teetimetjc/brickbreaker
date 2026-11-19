#!/usr/bin/env python3
"""
One-time TikTok connection: exchange the authorization code (shown on the website's callback page after the
operator approves the app) for tokens, save them encrypted to data/tiktok_token.enc, and confirm the account.
Run by the "TikTok connect" workflow (it has the secrets). Codes are single-use and expire within minutes.

  TIKTOK_CLIENT_KEY=... TIKTOK_CLIENT_SECRET=... python3 scripts/tiktok_connect.py --code '...'
  python3 scripts/tiktok_connect.py --url-for <client_key>   # just print the approval link
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from publishers import tiktok  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default="")
    ap.add_argument("--url-for", default="")
    a = ap.parse_args()
    if a.url_for:
        print(tiktok.authorize_url(a.url_for))
        return
    code = a.code.strip()
    if not code:
        sys.exit("pass --code")
    tok = tiktok.exchange_code(code)
    print(f"connected: scopes={tok.get('scope')} open_id=...{str(tok.get('open_id', ''))[-6:]}")
    try:
        print(f"account: {tiktok.whoami().get('display_name')}")
    except Exception as e:  # not fatal; the token is saved
        print(f"note: could not read profile ({e})")


if __name__ == "__main__":
    main()
