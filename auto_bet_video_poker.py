#!/usr/bin/env python3
"""
Auto-betting bot for just.bet (WINR Protocol) — Video Poker (Jacks or Better).

- Reads token from ./token.txt; if missing/invalid, does email+OTP login.
- On token expiry (401), silently refreshes via Privy (no OTP needed).
- Plays Video Poker: deals a hand, computes the mathematically optimal hold
  by brute-forcing ALL 2^5 = 32 hold combinations and, for each, enumerating
  every possible draw from the remaining 47-card deck to get the exact
  expected multiplier (EV). Picks the highest-EV hold — provably perfect
  for this paytable.
- Random 10-20s gap between bets; after every 30 bets, a 60-120s gap.
- On HTTP 429, waits 5 minutes and retries (repeats as needed).
- Stops if balance drops below MIN_BALANCE WINR.
- On reaching profit target (default +300 WINR), takes a 1-3 min break.
"""

import os
import sys
import time
import json
import random
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from itertools import combinations, combinations_with_replacement

# Make the justbet SDK importable
SDK_PATH = JUSTBET_DIRECTORY_PATH
if SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)

from justbet_sdk import JustBetAPI, JustBetError
from justbet_sdk.config import PRIVY_APP_ID

# Privy token refresh endpoint
_PRIVY_REFRESH_URL = "https://auth.privy.io/api/v1/sessions"

# ── Configuration ──────────────────────────────────────────────
TOKEN_FILE = "token.txt"
WAGER = 50
MIN_BALANCE = 200
BET_GAP_MIN = 10                # seconds between bets
BET_GAP_MAX = 20
BATCH_SIZE_MIN = 30
BATCH_SIZE_MAX = 30
BATCH_GAP_MIN = 60              # seconds between batches
BATCH_GAP_MAX = 120
RATE_LIMIT_WAIT = 300           # 5 minutes

# Profit target cooldown
PROFIT_TARGET = 300             # when net profit reaches this, take a break
PROFIT_WAIT_MIN = 60            # min seconds to wait (1 minute)
PROFIT_WAIT_MAX = 180           # max seconds to wait (3 minutes)

# IST offset
IST = timezone(timedelta(hours=5, minutes=30))


# ── Jacks or Better hand evaluator ─────────────────────────────
# Paytable multipliers indexed by hand category 0..9
# 0 No win | 1 JoB | 2 Two Pair | 3 Trips | 4 Straight | 5 Flush
# 6 Full House | 7 Quads | 8 Straight Flush | 9 Royal Flush
PAYOUT = [0, 1, 2, 3, 5, 6, 8, 25, 50, 100]

RANK_NAMES = "A23456789TJQK"   # internal rank 0..12  (SDK rank-1)
SUIT_NAMES = "HDCS"           # 0=Hearts, 1=Diamonds, 2=Clubs, 3=Spades

# One prime per rank. The product of 5 rank-primes uniquely encodes the rank
# multiset (fundamental theorem of arithmetic) — faster than sorting a tuple.
_PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]


def _build_rank_table():
    """Map rank-multiset prime-product key -> (non_flush_cat, is_straight, is_royal)."""
    table = {}
    for combo in combinations_with_replacement(range(13), 5):
        counts = [0] * 13
        key = 1
        for r in combo:
            counts[r] += 1
            key *= _PRIMES[r]
        cv = sorted(counts, reverse=True)
        c0, c1 = cv[0], cv[1]
        distinct = sum(1 for c in counts if c > 0)
        present = [i for i in range(13) if counts[i] > 0]
        is_straight = False
        is_royal = False
        if distinct == 5:
            sp = sorted(present)
            if sp[4] - sp[0] == 4:
                # five consecutive ranks (incl. wheel A-2-3-4-5)
                is_straight = True
            elif set(present) == {0, 9, 10, 11, 12}:
                # broadway A-T-J-Q-K (Ace plays high) -> royal ranks
                is_straight = True
                is_royal = True
        if is_straight:
            cat = 4                      # Straight
        elif c0 == 4:
            cat = 7                      # Four of a Kind
        elif c0 == 3 and c1 == 2:
            cat = 6                      # Full House
        elif c0 == 3:
            cat = 3                      # Three of a Kind
        elif c0 == 2 and c1 == 2:
            cat = 2                      # Two Pair
        elif c0 == 2:
            pair_rank = next(i for i in range(13) if counts[i] == 2)
            cat = 1 if pair_rank in (0, 10, 11, 12) else 0  # A,J,Q,K pay, else 0
        else:
            cat = 0                      # No win
        table[key] = (cat, is_straight, is_royal)
    return table


_RANK_TABLE = _build_rank_table()


def best_hold(cards):
    """
    cards: list of 5 (rank, suit) tuples, rank 0..12, suit 0..3.

    Brute-force all 32 hold masks. For each mask, enumerate every possible
    draw from the 47-card remaining deck and compute the exact expected
    multiplier (EV). Returns (best_mask, best_ev).
    """
    held_ranks = [c[0] for c in cards]
    held_suits = [c[1] for c in cards]
    hand_ids = set(r * 4 + s for r, s in cards)

    # Remaining 47-card deck (52 - 5 dealt)
    deck_ranks = [r for r in range(13) for s in range(4) if r * 4 + s not in hand_ids]
    deck_suits = [s for r in range(13) for s in range(4) if r * 4 + s not in hand_ids]
    deck_pr = [_PRIMES[r] for r in deck_ranks]
    n = 47

    RT = _RANK_TABLE
    PAY = PAYOUT
    PR = _PRIMES
    comb = combinations

    best_ev = -1.0
    best_mask = 0

    for mask in range(32):
        held_idx = [i for i in range(5) if mask & (1 << i)]
        h = len(held_idx)
        d = 5 - h
        hr = [held_ranks[i] for i in held_idx]
        hs = [held_suits[i] for i in held_idx]
        held_key = 1
        for r in hr:
            held_key *= PR[r]

        # Flush feasibility from held cards
        if h > 0:
            held_suit = hs[0]
            held_all_flush = all(s == held_suit for s in hs)
        else:
            held_suit = -1
            held_all_flush = True

        total = 0.0
        count = 0

        if d == 0:
            is_flush = held_all_flush and h == 5
            cat, is_str, is_royal = RT[held_key]
            if is_flush:
                cat = 9 if (is_str and is_royal) else (8 if is_str else 5)
            total = PAY[cat]
            count = 1
        elif d == 5:
            # hold nothing — all 5 drawn
            dp, ds = deck_pr, deck_suits
            for a, b, c, e, f in comb(range(n), 5):
                rk = dp[a] * dp[b] * dp[c] * dp[e] * dp[f]
                s0 = ds[a]
                if ds[b] == s0 and ds[c] == s0 and ds[e] == s0 and ds[f] == s0:
                    cat, is_str, is_royal = RT[rk]
                    cat = 9 if (is_str and is_royal) else (8 if is_str else 5)
                else:
                    cat = RT[rk][0]
                total += PAY[cat]
                count += 1
        elif d == 4:
            dp, ds = deck_pr, deck_suits
            hk, hsu, haf = held_key, held_suit, held_all_flush
            for a, b, c, e in comb(range(n), 4):
                rk = hk * dp[a] * dp[b] * dp[c] * dp[e]
                if haf:
                    if hsu == -1:
                        s0 = ds[a]
                        is_f = ds[b] == s0 and ds[c] == s0 and ds[e] == s0
                    else:
                        is_f = ds[a] == hsu and ds[b] == hsu and ds[c] == hsu and ds[e] == hsu
                else:
                    is_f = False
                if is_f:
                    cat, is_str, is_royal = RT[rk]
                    cat = 9 if (is_str and is_royal) else (8 if is_str else 5)
                else:
                    cat = RT[rk][0]
                total += PAY[cat]
                count += 1
        elif d == 3:
            dp, ds = deck_pr, deck_suits
            hk, hsu, haf = held_key, held_suit, held_all_flush
            for a, b, c in comb(range(n), 3):
                rk = hk * dp[a] * dp[b] * dp[c]
                if haf:
                    if hsu == -1:
                        s0 = ds[a]
                        is_f = ds[b] == s0 and ds[c] == s0
                    else:
                        is_f = ds[a] == hsu and ds[b] == hsu and ds[c] == hsu
                else:
                    is_f = False
                if is_f:
                    cat, is_str, is_royal = RT[rk]
                    cat = 9 if (is_str and is_royal) else (8 if is_str else 5)
                else:
                    cat = RT[rk][0]
                total += PAY[cat]
                count += 1
        elif d == 2:
            dp, ds = deck_pr, deck_suits
            hk, hsu, haf = held_key, held_suit, held_all_flush
            for a, b in comb(range(n), 2):
                rk = hk * dp[a] * dp[b]
                if haf:
                    if hsu == -1:
                        is_f = ds[a] == ds[b]
                    else:
                        is_f = ds[a] == hsu and ds[b] == hsu
                else:
                    is_f = False
                if is_f:
                    cat, is_str, is_royal = RT[rk]
                    cat = 9 if (is_str and is_royal) else (8 if is_str else 5)
                else:
                    cat = RT[rk][0]
                total += PAY[cat]
                count += 1
        else:  # d == 1
            dp, ds = deck_pr, deck_suits
            hk, hsu, haf = held_key, held_suit, held_all_flush
            for a in range(n):
                rk = hk * dp[a]
                if haf:
                    is_f = (hsu == -1) or (ds[a] == hsu)
                else:
                    is_f = False
                if is_f:
                    cat, is_str, is_royal = RT[rk]
                    cat = 9 if (is_str and is_royal) else (8 if is_str else 5)
                else:
                    cat = RT[rk][0]
                total += PAY[cat]
                count += 1

        ev = total / count
        if ev > best_ev:
            best_ev = ev
            best_mask = mask

    return best_mask, best_ev


def mask_to_hold(mask):
    """Convert a 5-bit mask into the SDK's [bool]*5 hold list."""
    return [(bool(mask & (1 << i))) for i in range(5)]


def card_label(rank, suit):
    return f"{RANK_NAMES[rank]}{SUIT_NAMES[suit]}"


def hold_desc(cards, hold_list):
    """Human-readable summary of which cards are kept vs discarded."""
    kept = [card_label(r, s) for (r, s), k in zip(cards, hold_list) if k]
    disc = [card_label(r, s) for (r, s), k in zip(cards, hold_list) if not k]
    return f"keep[{','.join(kept)}] disc[{','.join(disc)}]"


# ── Helpers ────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_tokens():
    """Load (access_token, refresh_token) from token.txt (JSON or legacy plain)."""
    if not os.path.exists(TOKEN_FILE):
        return None, None
    with open(TOKEN_FILE) as f:
        content = f.read().strip()
    if not content:
        return None, None
    try:
        data = json.loads(content)
        return data.get("access_token"), data.get("refresh_token")
    except json.JSONDecodeError:
        return content, None


def save_tokens(access_token, refresh_token):
    data = {"access_token": access_token}
    if refresh_token:
        data["refresh_token"] = refresh_token
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f)


def refresh_access_token(access_token, refresh_token):
    """Refresh via Privy. Returns (new_access, new_refresh) or (None, None)."""
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


# ── Authentication ─────────────────────────────────────────────
_email = None  # cached for OTP login fallback


def _login_with_otp_and_refresh():
    """Email+OTP login capturing both access and refresh tokens."""
    global _email
    if not _email:
        _email = input("Enter your email: ").strip()
    JustBetAPI.request_otp(_email)
    log(f"OTP sent to {_email}.")
    otp = input("Enter the OTP from your email: ").strip()

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
    try:
        api._post("/api/user/register", body={})
    except Exception:
        pass
    log("Login successful. Tokens saved to token.txt.")
    return api


def authenticate():
    """Try saved token -> refresh -> OTP login."""
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
def _api_call(api, fn):
    """Call fn(api) with 429 backoff and 401 re-auth. Returns (result, api)."""
    while True:
        try:
            return fn(api), api
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


def place_video_poker_round(api, wager):
    """
    Play one Video Poker round:
      1. place_bet -> deal 5 cards
      2. compute optimal hold via brute-force EV over all 32 masks
      3. video_poker_action(roundId, hold)
    Returns (result, api). The result dict is enriched with _dealt, _hold,
    _hold_mask, _ev, _hold_desc for logging.
    Mid-round 401/429 resumes the same round by roundId (wager already locked).
    """
    deal, api = _api_call(api, lambda a: a.place_bet("video_poker", wager_amount=wager))
    rid = deal["roundId"]

    # Parse dealt hand into internal (rank 0..12, suit 0..3)
    cards = [(c["rank"] - 1, c["suit"]) for c in deal["cardsView"]]

    t0 = time.perf_counter()
    mask, ev = best_hold(cards)
    dt = time.perf_counter() - t0
    hold_list = mask_to_hold(mask)

    result, api = _api_call(api, lambda a: a.video_poker_action(rid, hold_list))

    result["_dealt"] = cards
    result["_hold"] = hold_list
    result["_hold_mask"] = mask
    result["_ev"] = ev
    result["_ev_ms"] = dt * 1000
    result["_hold_desc"] = hold_desc(cards, hold_list)
    return result, api


# ── Main loop ──────────────────────────────────────────────────
def main():
    api = authenticate()

    balance = get_balance(api)
    start_balance = balance
    log(
        f"Starting balance: {balance:.2f} WINR | Game: video_poker | "
        f"Wager: {WAGER} | Strategy: optimal EV (32-mask brute force)"
    )
    if balance < MIN_BALANCE:
        log(f"Balance already below {MIN_BALANCE}. Stopping.")
        return

    batch_target = random.randint(BATCH_SIZE_MIN, BATCH_SIZE_MAX)
    games_in_batch = 0
    total_games = 0
    wins = 0

    try:
        while True:
            # Play one Video Poker round (deal -> optimal hold -> draw)
            result, api = place_video_poker_round(api, WAGER)
            won = result.get("won", False)
            profit = result.get("profit", 0)
            multiplier = result.get("multiplier", 0)
            rank_name = result.get("rankName", "?")
            # video_poker_action's balanceAfter is unreliable (server quirk),
            # so fetch the true balance after each round.
            balance = get_balance(api)
            total_games += 1
            games_in_batch += 1
            if won:
                wins += 1
            net_pnl = balance - start_balance

            dealt_str = " ".join(card_label(r, s) for r, s in result["_dealt"])
            log(
                f"Game {total_games}: dealt={dealt_str} | {result['_hold_desc']} "
                f"| EV={result['_ev']:.4f} ({result['_ev_ms']:.0f}ms) | "
                f"draw={rank_name} x{multiplier} | won={won} profit={profit:+.2f} "
                f"balance={balance:.2f} net={net_pnl:+.2f} ({wins}/{total_games})"
            )

            # Profit target reached — take a break
            if net_pnl >= PROFIT_TARGET:
                gap = random.randint(PROFIT_WAIT_MIN, PROFIT_WAIT_MAX)
                log(
                    f"Profit target hit (net={net_pnl:+.2f} >= +{PROFIT_TARGET}). "
                    f"Cooling down {gap}s..."
                )
                time.sleep(gap)

            # Stop if balance too low
            if balance < MIN_BALANCE:
                log(f"Balance {balance:.2f} below {MIN_BALANCE}. Stopping.")
                break

            # Choose gap
            if games_in_batch >= batch_target:
                gap = random.randint(BATCH_GAP_MIN, BATCH_GAP_MAX)
                log(f"Batch of {games_in_batch} games complete. Cooling down {gap}s...")
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
        f"Final balance: {balance:.2f} | Net: {net_pnl:+.2f} WINR | "
        f"Wins: {wins}/{total_games}"
    )


if __name__ == "__main__":
    main()
