# just.bet SDK — Agent Reference

## What this SDK does
Python SDK for interacting with just.bet (WINR Protocol).
Lets an AI agent authenticate, read game data, and place bets on behalf of the user.
Zero external dependencies — pure Python standard library.

## Install
```bash
pip install -e JUSTBET_DIRECTORY_PATH --break-system-packages
```

## Login flow for agents
The agent handles auth autonomously — the human only needs to provide an email
and enter the OTP once per session.

```
1. Agent checks /TEMPORARY_FOLDER(e.g. /tmp/)/justbet_token.txt for a saved token → load and use it.
2. If no token (or HTTP 401 on any call):
   a. Ask human for email if not already known.
   b. Call JustBetAPI.request_otp(email)  ← sends OTP to inbox.
   c. Ask human: "Enter the OTP from your email:"
   d. Call api = JustBetAPI.login_with_email(email, otp)
   e. Save api._token to /TEMPORARY_FOLDER(e.g. /tmp/)/justbet_token.txt for reuse.
3. Proceed with bets. On next run, step 1 skips the OTP entirely.
```

Token expires in ~1 hour. On expiry (HTTP 401) the agent repeats step 2.

## Complete workflow

```python
from justbet_sdk import JustBetAPI, GAME_IDS, get_game_id, VERIFIED_GAMES

# ── Step 1: Login (human-assisted — OTP sent to email) ────────────────────────
JustBetAPI.request_otp("user@email.com")
api = JustBetAPI.login_with_email("user@email.com", "123456")
# Or reuse a saved token:
# api = JustBetAPI(auth_token="eyJ...")

# ── Step 2: Check balance ──────────────────────────────────────────────────────
bal = api.get_balance()
# {"balance": 0, "usdc": 0, "winr": 4654.3}  — WINR is the in-platform currency

# ── Step 3: Check game config before betting ──────────────────────────────────
config = api.get_game_config(GAME_IDS["dice"]).get("data", {})
# {"minBet": 50, "maxBet": 500000, "maxPayout": 7792692.5, "topMultiplier": {...}}

# ── Step 4: Place bets (verified games only) ──────────────────────────────────
result = api.place_bet("dice",     wager_amount=50, target=81.91, direction="under")
result = api.place_bet("limbo",    wager_amount=50, target=2)
result = api.place_bet("coinflip", wager_amount=50, choice=1)        # 1=Heads, 0=Tails
result = api.place_bet("plinko",   wager_amount=50, rows=8)          # rows 6-12
result = api.place_bet("roll",     wager_amount=50, choices=[0,1,2,3])  # die face indices

# hilo is 2-step: start round, then take actions
round_info = api.place_bet("hilo", wager_amount=50)
result = api.hilo_action(round_info["roundId"], "lower")  # "higher"|"lower"|"same"

# ── Step 5: Check own bet history ─────────────────────────────────────────────
my_bets = api.get_my_bets(page=1, filter_="all")
# {"data": {"bets": [{id, gameId, gameName, wagerAmount, payoutAmount, multiplier, ...}]}}
```

## Supported games

### Verified (Burp-confirmed request/response, June 2026)
Only these 6 games should be used for betting:

| Slug       | Key params                                          | Notes                          |
|------------|-----------------------------------------------------|--------------------------------|
| `dice`     | `target` (float 0–100), `direction` ("under"\|"over") | Win if roll is under/over target |
| `limbo`    | `target` (float multiplier, e.g. 2.0)              | Win if crash point ≥ target    |
| `coinflip` | `choice` (0=Tails, 1=Heads)                         | 50/50                          |
| `plinko`   | `rows` (int 6–12)                                   | More rows = wider payout range |
| `roll`     | `choices` (list of face indices 0–5)                | Pick which die faces win       |
| `hilo`     | none for start; `action` ("higher"\|"lower"\|"same") for each step | Multi-step card game |

### Original games — unverified (do not bet on these)
`keno`, `roulette`, `wheel`, `holdem`, `blackjack`, `video_poker`, `baccarat` are
the remaining 7 original JustBet games. Their request/response formats have not
been captured from Burp and may differ — do not call `place_bet` on them.

## All methods

### Authentication (static)
```python
JustBetAPI.request_otp(email)                          # send OTP to email → bool
api = JustBetAPI.login_with_email(email, otp_code)     # returns authenticated instance
api = JustBetAPI(auth_token="eyJ...")                  # reuse saved Privy JWT
```

### Betting (requires auth)
```python
# ── Standard single-round games ───────────────────────────────────────────────
api.place_bet("dice",     wager_amount=50, target=81.91, direction="under")
api.place_bet("limbo",    wager_amount=50, target=2)
api.place_bet("coinflip", wager_amount=50, choice=1)
api.place_bet("plinko",   wager_amount=50, rows=8)
api.place_bet("roll",     wager_amount=50, choices=[0,1,2,3])

# ── HiLo (multi-step) ─────────────────────────────────────────────────────────
round_info = api.place_bet("hilo", wager_amount=50)
# round_info: roundId, startCard {index,rank,suit}, odds {higher,lower,same},
#             currentMultiplier, balanceAfter

result = api.hilo_action(round_id, action)
# action: "higher" | "lower" | "same"
# result: state ("OPEN"=continue | "CLOSED"=done), card, outcome, correct,
#         currentMultiplier, payoutAmount, profit, won, balanceAfter
# When state="CLOSED": serverSeedRevealed is included for provable fairness
```

### Bet result structure (standard games — verified)
```python
{
  "betId":           "de4f09f9-...",
  "roundId":         "de4f09f9-...",
  "game":            {"id": "e5b85122-...", "name": "Roll"},
  "wagerAmount":     50,
  "payoutAmount":    73.5,
  "profit":          23.5,
  "multiplier":      1.47,
  "result":          {...},       # game-specific (see per-game result below)
  "fairness":        {"scheme": "COMMIT_REVEAL", "algorithm": "HMAC_SHA256",
                      "serverSeedHash": "...", "clientSeed": "...",
                      "nonce": 5, "output": "..."},
  "balanceAfter":    4622.8,
  "wasMaxWinCapped": False,
  "uncappedPayout":  73.5,
  "maxPayout":       7792692.5,
  "createdAt":       "2026-06-25T15:34:56.570Z"
}
# Check result["result"]["won"] for win/loss
```

### Per-game result objects
```python
# dice
{"target": 81.91, "direction": "under", "choice": 8191, "result": 9525,
 "rollValue": 95.25, "winChance": 81.91, "won": False}

# limbo
{"target": 2, "choice": 200, "rolled": 6828, "rolledMultiplier": 68.28, "won": True}

# coinflip
{"choice": 0, "result": 1, "winChance": 50, "won": False}

# plinko
{"rows": 8, "path": [0,0,1,0,0,1,0,0], "bucket": 2, "multiplier": 0.9, "won": False}

# roll
{"choices": [0,1,2,3], "result": 2, "won": True, "pickCount": 4}
```

### User & balance (requires auth)
```python
api.get_balance()
# {"balance": 0, "usdc": 0, "winr": 4654.3}

api.get_user_me()
# data: id, walletAddress, username, vipLevel, totalBets, totalVolume,
#       totalProfit, balance, cardsTitle, joinedAt

api.get_user_profile("0x...")
# data: address, level, username, bio, stats {games, bets, volume}

api.get_user_history("0x...", filter_="all")
# data.games (list), data.count, data.pageCount, data.is_player_exist

api.get_my_bets(page=1, filter_="all")
# data.bets (list), data.count, data.pageCount

api.get_strategies()          # data.strategies (list)
api.get_daily_rewards()       # streakDays, isClaimableNow, nextClaimDay, ladder
api.get_quests()              # quests (list)
api.get_chat_messages(channel_id="general")  # data.messages (list)
```

### Staking (requires auth)
```python
api.get_stake_balance()    # {"balance", "lifetimeEarned", "lifetimeSpent"}
api.get_stake_holdings()
api.get_stake_ledger()
api.get_stake_boosters()
```

### Games & leaderboards (public — no login needed)
```python
api.get_games_popular(limit=20)
api.get_games_trending(limit=20)
api.get_games_new(limit=20)
api.get_game_detail("dice")               # full metadata for a game by slug
api.get_game_config(GAME_IDS["dice"])     # minBet, maxBet, maxPayout, topMultiplier
api.get_high_rollers(game_id=GAME_IDS["dice"], per_page=10)
api.get_lucky_winners(per_page=10)
api.get_leaderboard_top_games(window="30d")    # window: "24h"|"7d"|"30d"|"all"
api.get_leaderboard_top_creators(window="30d")
api.get_leaderboard_top_earners()
```

### WINR Protocol analytics (public)
```python
api.get_token_prices()    # USD prices for WINR, USDC, etc.
api.get_protocol_stats()  # global protocol stats
```

## Roll game — how choices work
`roll` is a 6-sided die game. Pick which faces you want to win on:
- Face indices: 0=1, 1=2, 2=3, 3=4, 4=5, 5=6
- More faces = higher win probability, lower multiplier
- `choices=[0,1,2,3]` → 4/6 faces → ~66.7% win chance, ~1.47x multiplier
- `choices=[5]` → 1/6 faces → ~16.7% win chance, ~5.88x multiplier

## Game IDs (verified June 2026)
```python
from justbet_sdk import GAME_IDS, ORIGINAL_GAMES, VERIFIED_GAMES, get_game_id

VERIFIED_GAMES   # ["dice", "limbo", "coinflip", "plinko", "roll", "hilo"]
ORIGINAL_GAMES   # all 13 original JustBet slugs

get_game_id("dice")      # "5b55ea3a-2f90-4c7d-bf4f-18665fd4028e"
get_game_id("limbo")     # "4b2e766d-768a-4c25-9169-b356eb6e978b"
get_game_id("coinflip")  # "2d1815d3-d86a-45cd-8a02-96984ea5fada"
get_game_id("plinko")    # "dc48ab77-1288-4d4d-9f2a-cb21393135b8"
get_game_id("roll")      # "e5b85122-816d-4455-b279-d025768b9e68"
get_game_id("hilo")      # "a7ff9d78-4fca-485f-b386-ed8ea49a9fec"
```

## Verified addresses
```python
from justbet_sdk import TOKENS, PROTOCOL_ADDRESSES, JUSTBET_API_BASE_URL, PRIVY_APP_ID

TOKENS["USDC"]                    # 0xaf88d065e77c8cC2239327C5EDb3A432268e5831
TOKENS["WINR"]                    # 0xD77B108d4f6cefaa0Cae9506A934e825BEccA46E
PROTOCOL_ADDRESSES["cashier"]     # 0x4685AcE4e80144E2Fd23380Cf76bd36e47a838Fb
PROTOCOL_ADDRESSES["bankroll"]    # 0xFFBC24fbe694b15093d8233476CD27ED9e9C778C
JUSTBET_API_BASE_URL              # https://jb-development-eqoyn.ondigitalocean.app
PRIVY_APP_ID                      # cmnd3ngp901ty0clb9rknxcxi
```

## Error handling
```python
import urllib.error
from justbet_sdk import JustBetError

try:
    result = api.place_bet("dice", wager_amount=50, target=50.0, direction="under")
except urllib.error.HTTPError as e:
    if e.code == 402:
        print("Insufficient balance — deposit funds first")
    elif e.code == 401:
        print("Auth token expired — re-authenticate")
    else:
        print(f"HTTP error {e.code}")
except JustBetError as e:
    print(f"SDK error: {e}")
```
