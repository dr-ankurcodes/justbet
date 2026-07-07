#!/usr/bin/env python3
"""
Auto-betting bot for just.bet (WINR Protocol).

- Reads token from ./token.txt; if missing/invalid, does email+OTP login.
- On token expiry (401), silently refreshes via Privy (no OTP needed).
- Plays the Roll game on configurable faces at a configurable wager per bet.
- Random 10-20s gap between bets; after every 30-35 bets, a 10-20s gap.
- On HTTP 429, waits 5 minutes and retries (repeats as needed).
- Stops if balance drops below 2000 WINR.
- Supports static or dynamic face selection (re-evaluates every 10 games).
- On reaching profit target (default +200 WINR), takes a 1-3 min break and
  resets dynamic choices back to the initial config.
"""

import os
import sys
import time
import json
import random
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

# Make the justbet SDK importable
SDK_PATH = "JUSTBET_DIRECTORY_PATH"
if SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)

from justbet_sdk import JustBetAPI, JustBetError
from justbet_sdk.config import PRIVY_APP_ID

# Privy token refresh endpoint
_PRIVY_REFRESH_URL = "https://auth.privy.io/api/v1/sessions"

# ── Configuration ──────────────────────────────────────────────
TOKEN_FILE = "token.txt"
WAGER = 100
CHOICES = [0, 1, 2, 3]          # roll faces 1,2,3,4
MODE = "static"                # "static" or "dynamic"
                                # static  = always bet on CHOICES
                                # dynamic = use CHOICES for first 10 games,
                                #           then pick the N least-frequent faces
                                #           from the last 10 results every 10 games
MIN_BALANCE = 2000
BET_GAP_MIN = 10                # seconds between bets
BET_GAP_MAX = 20
BATCH_SIZE_MIN = 30
BATCH_SIZE_MAX = 30
BATCH_GAP_MIN = 60              # seconds between batches
BATCH_GAP_MAX = 120
RATE_LIMIT_WAIT = 300           # 5 minutes
DYNAMIC_WINDOW = 30             # re-evaluate every N games

# Profit target cooldown
PROFIT_TARGET = 300             # when net profit reaches this, take a break
PROFIT_WAIT_MIN = 60            # min seconds to wait (1 minute)
PROFIT_WAIT_MAX = 180           # max seconds to wait (3 minutes)

# IST offset
IST = timezone(timedelta(hours=5, minutes=30))


# ── Helpers ────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_tokens():
    """
    Load access_token and refresh_token from token.txt.
    Supports both JSON format (new) and plain-text (legacy).
    Returns (access_token, refresh_token) — refresh_token may be None.
    """
    if not os.path.exists(TOKEN_FILE):
        return None, None
    with open(TOKEN_FILE) as f:
        content = f.read().strip()
    if not content:
        return None, None
    # Try JSON first
    try:
        data = json.loads(content)
        return data.get("access_token"), data.get("refresh_token")
    except json.JSONDecodeError:
        # Legacy format: just the access token as plain text
        return content, None


def save_tokens(access_token, refresh_token):
    """Save both tokens as JSON for future-proofing."""
    data = {"access_token": access_token}
    if refresh_token:
        data["refresh_token"] = refresh_token
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f)


def refresh_access_token(access_token, refresh_token):
    """
    Call Privy's token refresh endpoint to get a new access token.
    Requires BOTH the current access_token (in Authorization header)
    AND the refresh_token (in body).
    Returns (new_access_token, new_refresh_token) or (None, None) on failure.
    """
    body = json.dumps({"refresh_token": refresh_token}).encode()
    req = urllib.request.Request(
        _PRIVY_REFRESH_URL, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Privy-App-Id": PRIVY_APP_ID,
            "Privy-Client": "react-auth:3.18.0",
            "Authorization": f"Bearer {access_token}",
            "Origin": "https://www.just.bet",
            "Referer": "https://www.just.bet/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        new_access = data.get("token") or data.get("privy_access_token")
        new_refresh = data.get("refresh_token")
        if new_access:
            return new_access, new_refresh
    except urllib.error.HTTPError as e:
        log(f"Token refresh failed: HTTP {e.code}")
    except Exception as e:
        log(f"Token refresh failed: {e}")
    return None, None


def get_balance(api):
    resp = api.get_balance()
    return resp.get("winr", 0)


def faces_label(choices):
    """Return e.g. 'faces [1, 2, 3, 4]' from choices [0,1,2,3]."""
    return str([c + 1 for c in sorted(choices)])


def pick_dynamic_choices(last_results, n):
    """
    From the last DYNAMIC_WINDOW results, find the (6 - n) face indices
    that appeared the *least* often, then AVOID those — bet on the
    remaining n faces (the most frequent ones).  Ties broken by lower
    index first among the avoided set.
    """
    window = last_results[-DYNAMIC_WINDOW:]
    counts = {i: 0 for i in range(6)}
    for face in window:
        counts[face] += 1
    # Rank by least frequent (these are the ones we avoid)
    avoid_count = 6 - n
    ranked = sorted(counts.keys(), key=lambda f: (counts[f], f))
    avoided = ranked[:avoid_count]
    # Pick everything except the avoided faces
    return [f for f in range(6) if f not in avoided]


# ── Authentication ─────────────────────────────────────────────
_email = None  # cached for OTP login fallback


def _login_with_otp_and_refresh():
    """
    Perform email+OTP login, capturing both access_token and refresh_token.
    Returns an authenticated JustBetAPI with tokens saved.
    """
    global _email
    if not _email:
        _email = input("Enter your email: ").strip()
    JustBetAPI.request_otp(_email)
    log(f"OTP sent to {_email}.")
    otp = input("Enter the OTP from your email: ").strip()

    # Make the raw request to capture refresh_token (SDK discards it)
    url = "https://auth.privy.io/api/v1/passwordless/authenticate"
    body = json.dumps({
        "email": _email, "code": otp, "mode": "login-or-sign-up",
    }).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Privy-App-Id": PRIVY_APP_ID,
            "Privy-Client": "react-auth:3.18.0",
            "Origin": "https://www.just.bet",
            "Referer": "https://www.just.bet/",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    access_token = data.get("token") or data.get("privy_access_token")
    refresh_token = data.get("refresh_token")
    if not access_token:
        raise ValueError(f"Privy login failed — no token in response. Keys: {list(data.keys())}")

    save_tokens(access_token, refresh_token)
    api = JustBetAPI(auth_token=access_token)
    # Activate session on just.bet backend
    try:
        api._post("/api/user/register", body={})
    except Exception:
        pass
    log("Login successful. Tokens saved to token.txt.")
    return api


def authenticate():
    """
    Try saved tokens in this order:
    1. access_token still valid → use it
    2. access_token expired but refresh_token exists → refresh silently
    3. No valid tokens → email+OTP login
    """
    access_token, refresh_token = load_tokens()

    if access_token:
        api = JustBetAPI(auth_token=access_token)
        try:
            get_balance(api)
            log("Loaded saved token — valid.")
            return api
        except urllib.error.HTTPError as e:
            if e.code == 401:
                log("Access token expired.")
            else:
                raise

        # Try refresh
        if refresh_token:
            log("Attempting silent token refresh...")
            new_access, new_refresh = refresh_access_token(access_token, refresh_token)
            if new_access:
                api = JustBetAPI(auth_token=new_access)
                try:
                    get_balance(api)
                    save_tokens(new_access, new_refresh or refresh_token)
                    log("Token refreshed successfully.")
                    return api
                except Exception as e:
                    log(f"Refreshed token failed validation: {e}")
            else:
                log("Refresh token also expired or invalid.")

    # Fall back to OTP login
    log("No valid tokens. Proceeding to email+OTP login.")
    return _login_with_otp_and_refresh()


def reauthenticate():
    """Re-authenticate mid-session: try refresh first, then OTP."""
    access_token, refresh_token = load_tokens()
    if access_token and refresh_token:
        log("Token expired. Attempting silent refresh...")
        new_access, new_refresh = refresh_access_token(access_token, refresh_token)
        if new_access:
            api = JustBetAPI(auth_token=new_access)
            try:
                get_balance(api)
                save_tokens(new_access, new_refresh or refresh_token)
                log("Token refreshed successfully.")
                return api
            except Exception as e:
                log(f"Refreshed token invalid: {e}")

    log("Refresh failed or unavailable. Falling back to email+OTP.")
    return _login_with_otp_and_refresh()


# ── Bet placement with retry ───────────────────────────────────
def place_bet_retry(api, choices):
    """Place a bet; on 429 wait 5 min and retry, on 401 re-auth."""
    while True:
        try:
            result = api.place_bet("roll", wager_amount=WAGER, choices=choices)
            return result, api
        except urllib.error.HTTPError as e:
            if e.code == 429:
                log("HTTP 429 — rate limited. Waiting 5 minutes...")
                time.sleep(RATE_LIMIT_WAIT)
                continue
            elif e.code == 401:
                api = reauthenticate()
                continue
            else:
                log(f"HTTP error {e.code}: {e}")
                raise
        except JustBetError as e:
            log(f"SDK error: {e}")
            raise


# ── Main loop ──────────────────────────────────────────────────
def main():
    api = authenticate()

    balance = get_balance(api)
    start_balance = balance
    log(f"Starting balance: {balance} WINR | Mode: {MODE} | Initial choices: {faces_label(CHOICES)}")
    if balance < MIN_BALANCE:
        log(f"Balance already below {MIN_BALANCE}. Stopping.")
        return

    batch_target = random.randint(BATCH_SIZE_MIN, BATCH_SIZE_MAX)
    games_in_batch = 0
    total_games = 0

    # Dynamic-mode state
    current_choices = list(CHOICES)
    last_results = []   # rolling list of face indices (0-5)

    try:
        while True:
            # Place one bet with current choices
            result, api = place_bet_retry(api, current_choices)
            won = result["result"]["won"]
            profit = result["profit"]
            balance = result["balanceAfter"]
            total_games += 1
            games_in_batch += 1
            face = result["result"]["result"]  # 0-5 internally
            face_display = face + 1             # 1-6 for human display
            net_pnl = balance - start_balance

            # Track result for dynamic mode
            if MODE == "dynamic":
                last_results.append(face)

            log(
                f"Game {total_games}: faces={faces_label(current_choices)} "
                f"face={face_display} won={won} "
                f"profit={profit:+.2f} balance={balance:.2f} "
                f"net={net_pnl:+.2f}"
            )

            # Profit target reached — take a break and reset dynamic choices
            if net_pnl >= PROFIT_TARGET:
                gap = random.randint(PROFIT_WAIT_MIN, PROFIT_WAIT_MAX)
                log(
                    f"Profit target hit (net={net_pnl:+.2f} >= +{PROFIT_TARGET}). "
                    f"Cooling down {gap}s..."
                )
                time.sleep(gap)
                if MODE == "dynamic":
                    current_choices = list(CHOICES)
                    last_results = []
                    log(f"Dynamic choices reset to initial: {faces_label(CHOICES)}")

            # Stop if balance too low
            if balance < MIN_BALANCE:
                log(f"Balance {balance:.2f} below {MIN_BALANCE}. Stopping.")
                break

            # Dynamic mode: re-evaluate choices every DYNAMIC_WINDOW games
            if MODE == "dynamic" and total_games % DYNAMIC_WINDOW == 0:
                current_choices = pick_dynamic_choices(last_results, len(CHOICES))
                log(
                    f"Dynamic reset after game {total_games}: "
                    f"last 10 faces={[r+1 for r in last_results[-DYNAMIC_WINDOW:]]} "
                    f"-> new choices {faces_label(current_choices)}"
                )

            # Choose gap
            if games_in_batch >= batch_target:
                gap = random.randint(BATCH_GAP_MIN, BATCH_GAP_MAX)
                log(
                    f"Batch of {games_in_batch} games complete. "
                    f"Cooling down {gap}s..."
                )
                time.sleep(gap)
                games_in_batch = 0
                batch_target = random.randint(BATCH_SIZE_MIN, BATCH_SIZE_MAX)
            else:
                gap = random.randint(BET_GAP_MIN, BET_GAP_MAX)
                time.sleep(gap)

    except KeyboardInterrupt:
        log("Interrupted by user. Stopping.")

    net_pnl = balance - start_balance
    log(
        f"Total games played: {total_games}. "
        f"Final balance: {balance:.2f} | Net: {net_pnl:+.2f} WINR"
    )


if __name__ == "__main__":
    main()
