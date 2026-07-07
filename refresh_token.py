#!/usr/bin/env python3
"""One-off: refresh the access token in token.txt via Privy."""
import json
import urllib.error
import urllib.request

from auto_bet_hilo import (
    load_tokens, save_tokens, refresh_access_token, get_balance, log,
)
from justbet_sdk import JustBetAPI


def main():
    access_token, refresh_token = load_tokens()
    if not access_token or not refresh_token:
        log("Missing access_token or refresh_token in token.txt — cannot refresh.")
        return 1

    log("Calling Privy refresh endpoint...")
    new_access, new_refresh = refresh_access_token(access_token, refresh_token)
    if not new_access:
        log("Refresh failed — no new access token returned.")
        return 1

    # Validate the new token against the just.bet backend
    api = JustBetAPI(auth_token=new_access)
    try:
        bal = get_balance(api)
    except urllib.error.HTTPError as e:
        log(f"Refreshed token failed validation: HTTP {e.code}")
        return 1

    save_tokens(new_access, new_refresh or refresh_token)
    log(f"Token refreshed and saved. Balance: {bal} WINR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
