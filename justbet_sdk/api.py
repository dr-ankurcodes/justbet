"""
REST API client for the just.bet backend.

VERIFIED from live Burp Suite traffic analysis of just.bet (June 2026).

═══════════════════════════════════════════════════════════════════════════════
PRIMARY BACKEND  https://jb-development-eqoyn.ondigitalocean.app
═══════════════════════════════════════════════════════════════════════════════

Despite the "development" subdomain, this is just.bet's live production API.
It handles all game sessions, bet history, user profiles, balances, and staking.

AUTHENTICATION  (verified from Burp)
──────────────
just.bet uses Privy for auth (app ID: cmnd3ngp901ty0clb9rknxcxi).

Step 1 — Request OTP:
  POST https://auth.privy.io/api/v1/passwordless/init
  Headers: Privy-App-Id: cmnd3ngp901ty0clb9rknxcxi, Content-Type: application/json
  Body: {"email": "your@email.com"}
  Response: {"success": true}

Step 2 — Verify OTP:
  POST https://auth.privy.io/api/v1/passwordless/authenticate
  Headers: Privy-App-Id: cmnd3ngp901ty0clb9rknxcxi, Content-Type: application/json
  Body: {"email": "your@email.com", "code": "123456", "mode": "login-or-sign-up"}
  Response: {"token": "eyJ...", "user": {"linked_accounts": [...]}}

Step 3 — Use the token:
  Pass token as: Authorization: Bearer eyJ...
  Also call POST /api/user/register with {} body to register the session.

Use JustBetAPI.login_with_email(email, otp_code) for a one-call helper.

BET PLACEMENT  (verified from Burp — all 6 games captured June 2026)
─────────────
All games: POST /api/archetype/{slug}/play

  dice:     {"slug":"dice",     "wagerAmount":"50", "target":81.91, "direction":"under"}
  limbo:    {"slug":"limbo",    "wagerAmount":"50", "target":2}
  coinflip: {"slug":"coinflip", "wagerAmount":"50", "choice":0}
  plinko:   {"slug":"plinko",   "wagerAmount":"50", "rows":8}
  roll:     {"slug":"roll",     "wagerAmount":"50", "choices":[0,1,2,3]}
  hilo:     {"slug":"hilo",     "wagerAmount":"50"}   ← starts round, no target
              then POST /api/archetype/hilo/action: {"roundId":"...", "action":"higher"}

  wagerAmount — string, WINR display units (min 50, max 500000)
  target      — float for dice (e.g. 81.91) or float for limbo (e.g. 2.0)
  direction   — "under"|"over" (dice only)
  choice      — 0=Tails, 1=Heads (coinflip only, singular)
  rows        — int 6-12 (plinko only)
  choices     — list of die face indices 0-5 (roll only)

  Standard success response keys: betId, roundId, game, wagerAmount,
    payoutAmount, profit, multiplier, result (game-specific), fairness,
    balanceAfter, wasMaxWinCapped, uncappedPayout, maxPayout, createdAt
  HTTP 402 if balance insufficient.

  hilo /play response: roundId, state("OPEN"), startCard, currentMultiplier,
    odds (higher/lower/same with p and multiplier), fairness, balanceAfter
  hilo /action response: roundId, state("OPEN"|"CLOSED"), action, card,
    outcome, correct, currentMultiplier, payoutAmount, profit, won,
    balanceAfter, wasMaxWinCapped, serverSeedRevealed (when CLOSED)

PUBLIC ENDPOINTS (no auth needed):
  /api/games/most-popular, /api/games/trending, /api/games/new-releases
  /api/games/{uuid}/config, /api/history/high-rollers, /api/history/lucky-winners
  /ai/games/detail
  /api/leaderboard/top-games, /api/leaderboard/top-creators
  /api/leaderboard/top-credit-earners

AUTHENTICATED ENDPOINTS (require Bearer token):
  /api/archetype/{slug}/play  — PLACE A BET
  /api/archetype/hilo/action  — HILO STEP
  /api/balance, /api/user/me, /api/user/history, /api/me/bets
  /api/user/register, /api/strategies
  /api/cards/daily-rewards, /api/cards/quests
  /api/stake/balance, /api/stake/holdings, /api/stake/ledger
  /api/chat/messages

CURRENCY
─────────
All wager/payout amounts use WINR display units.
Minimum bet: 50.  Maximum bet: 500000.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.parse
from typing import Any, Dict, List, Optional

from justbet_sdk.config import JUSTBET_API_BASE_URL, WINR_GATEWAY_URL, PRIVY_APP_ID

logger = logging.getLogger(__name__)

# Privy auth base URL
_PRIVY_BASE = "https://auth.privy.io"


class JustBetAPI:
    """
    HTTP client for the just.bet backend API.

    Public read-only endpoints work without authentication.
    Authenticated endpoints require a Privy JWT access token.

    Parameters
    ----------
    auth_token : str, optional
        Privy JWT token from the login response.
        Required for balance, bet history, staking, and bet placement.
    base_url : str
        Backend base URL (default: https://jb-development-eqoyn.ondigitalocean.app).
    timeout : int
        HTTP request timeout in seconds (default: 15).

    Example
    -------
    # No auth — public endpoints only
    api = JustBetAPI()
    config = api.get_game_config("5b55ea3a-2f90-4c7d-bf4f-18665fd4028e")  # dice

    # With auth
    api = JustBetAPI(auth_token="eyJ...")
    balance = api.get_balance()
    """

    def __init__(
        self,
        auth_token: Optional[str] = None,
        base_url: str = JUSTBET_API_BASE_URL,
        timeout: int = 15,
    ) -> None:
        self._base    = base_url.rstrip("/")
        self._token   = auth_token
        self._timeout = timeout

    # ── internals ─────────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        body: Optional[Dict] = None,
    ) -> Any:
        url = f"{self._base}/{path.lstrip('/')}"
        if params:
            clean = {k: str(v) for k, v in params.items() if v is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"

        headers: Dict[str, str] = {
            "Accept":       "application/json",
            "Content-Type": "application/json",
            "User-Agent":   "justbet-sdk/0.1.0",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        data = json.dumps(body).encode() if body else None
        req  = urllib.request.Request(url, data=data, headers=headers, method=method)

        logger.debug("%s %s", method, url)
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: Dict) -> Any:
        return self._request("POST", path, body=body)

    # ── game catalogue (public) ───────────────────────────────────────────────

    def get_games_popular(self, page: int = 1, limit: int = 20) -> Dict:
        """
        Return the most popular games.

        Returns dict with keys: ``data`` (list of game objects), ``total``.
        Each game has: id, slug, name, archetype, category, images, etc.
        """
        return self._get("/api/games/most-popular",
                         params={"page": page, "limit": limit, "includeNsfw": "false"})

    def get_games_trending(self, page: int = 1, limit: int = 20) -> Dict:
        """Return currently trending games."""
        return self._get("/api/games/trending",
                         params={"page": page, "limit": limit, "includeNsfw": "false"})

    def get_games_new(self, page: int = 1, limit: int = 20) -> Dict:
        """Return newest game releases."""
        return self._get("/api/games/new-releases",
                         params={"page": page, "limit": limit, "includeNsfw": "false"})

    def get_game_detail(self, slug: str) -> Dict:
        """
        Return full metadata for a game by slug.

        Parameters
        ----------
        slug : str  e.g. "coinflip", "dice", "limbo", "wheel"

        Returns dict: id, name, slug, archetype, category, presentation,
                      images, bundleUrl, status, isActive, etc.
        """
        return self._get("/ai/games/detail", params={"slug": slug})

    def get_game_config(self, game_id: str) -> Dict:
        """
        Return betting configuration for a game.

        Parameters
        ----------
        game_id : str
            Internal game UUID. Use ``justbet_sdk.game_ids.GAME_IDS`` to
            look up the UUID from a slug.

        Returns dict with: minBet, maxBet, maxPayout, topMultiplier
        (topMultiplier includes: multiplier, playerDisplayName,
         playerWalletAddress, payoutAmount, betCreatedAt).
        """
        return self._get(f"/api/games/{game_id}/config")

    # ── leaderboards / history (public) ──────────────────────────────────────

    def get_high_rollers(
        self,
        game_id: Optional[str] = None,
        page: int = 1,
        per_page: int = 10,
    ) -> Dict:
        """
        Return highest-wager bets, optionally filtered to one game.

        Parameters
        ----------
        game_id : str, optional
            Internal game UUID (see ``justbet_sdk.game_ids.GAME_IDS``).

        Returns dict:
            data.bets  — list of bet objects
            data.total — total count

        Each bet has: id, gameId, gameName, walletAddress, walletTruncated,
                      displayName, vipLevel, wagerAmount, payoutAmount,
                      multiplier, currency, createdAt.
        """
        params: Dict = {"page": page, "perPage": per_page}
        if game_id:
            params["gameId"] = game_id
        return self._get("/api/history/high-rollers", params=params)

    def get_lucky_winners(self, page: int = 1, per_page: int = 10) -> Dict:
        """Return bets with the highest payout multipliers."""
        return self._get("/api/history/lucky-winners",
                         params={"page": page, "perPage": per_page})

    # ── authenticated: user & balance ────────────────────────────────────────

    def get_balance(self) -> Dict:
        """
        Return the authenticated user's internal balance.

        Requires ``auth_token``.
        Returns: { "balance": float, "usdc": float, "winr": float }
        """
        return self._get("/api/balance")

    def get_user_me(self) -> Dict:
        """
        Return the authenticated user's profile.

        Requires ``auth_token``.
        Returns data: id, walletAddress, username, vipLevel, totalBets,
                      totalVolume, totalProfit, balance, cardsTitle, joinedAt.
        """
        return self._get("/api/user/me")

    def get_user_profile(self, wallet_address: str) -> Dict:
        """
        Return a public user profile by wallet address.

        Parameters
        ----------
        wallet_address : str  Checksummed Ethereum address.

        Returns data: address, level, username, bio, stats (games, bets, volume).
        """
        return self._get("/api/user", params={"address": wallet_address})

    def get_user_history(
        self,
        player: str,
        page: int = 1,
        filter_: str = "all",
    ) -> Dict:
        """
        Return bet history for a wallet address.

        Parameters
        ----------
        player : str    Checksummed wallet address.
        filter_ : str   "all" | "wins" | "losses"

        Returns dict:
            data.games — list of bet objects
            data.count, data.pageCount, data.is_player_exist
        """
        return self._get("/api/user/history",
                         params={"player": player, "page": page, "filter": filter_})

    def get_strategies(self) -> Dict:
        """Return saved betting strategies for the authenticated user."""
        return self._get("/api/strategies")

    # ── authenticated: staking & rewards ─────────────────────────────────────

    def get_stake_balance(self) -> Dict:
        """
        Return staking balance.
        Keys: balance, lifetimeEarned, lifetimeSpent.
        """
        return self._get("/api/stake/balance")

    def get_stake_holdings(self) -> Dict:
        """Return active stake positions."""
        return self._get("/api/stake/holdings")

    def get_stake_ledger(self, limit: int = 10) -> Dict:
        """Return staking transaction ledger."""
        return self._get("/api/stake/ledger", params={"limit": limit})

    def get_stake_boosters(self) -> Dict:
        """Return active staking boosters."""
        return self._get("/api/stake/boosters/active")

    def get_daily_rewards(self) -> Dict:
        """
        Return daily reward streak status.

        Keys: streakDays, nextClaimDay, isClaimableNow, cyclesCompleted,
              cycleMultiplier, streakProtectsAvailable, etc.
        """
        return self._get("/api/cards/daily-rewards")

    def get_quests(self) -> Dict:
        """Return active quest list and reset timer."""
        return self._get("/api/cards/quests")

    # ── bet placement (VERIFIED from Burp — 6 games, June 2026) ──────────────

    def place_bet(
        self,
        slug: str,
        wager_amount: int,
        target: Optional[float] = None,
        direction: Optional[str] = None,
        choice: Optional[int] = None,
        rows: Optional[int] = None,
        choices: Optional[List[int]] = None,
    ) -> Dict:
        """
        Place a bet on a game.  Requires ``auth_token``.

        VERIFIED endpoint: POST /api/archetype/{slug}/play
        VERIFIED games (Burp, June 2026): dice, limbo, coinflip, plinko, roll, hilo.

        Parameters
        ----------
        slug : str
            Verified game slugs: "dice", "limbo", "coinflip", "plinko", "roll".
            For hilo, use place_bet("hilo", wager_amount) then hilo_action().

        wager_amount : int
            Bet size in WINR display units. Min: 50, Max: 500000.

        target : float, optional
            - dice:  win threshold (e.g. 81.91 = win if roll < 81.91 with direction="under")
            - limbo: target multiplier (e.g. 2 = win if crash point >= 2.0x)

        direction : str, optional
            "under" or "over". Required for dice.

        choice : int, optional
            coinflip only. 0 = Tails, 1 = Heads.

        rows : int, optional
            plinko only. Number of peg rows: 6-12.

        choices : list of int, optional
            roll only. Die face indices to bet on (0=1, 1=2, 2=3, 3=4, 4=5, 5=6).
            Example: [0,1,2,3] bets on 4 faces (values 1-4).

        Returns
        -------
        dict
            betId, roundId, game, wagerAmount, payoutAmount, profit, multiplier,
            result (game-specific), fairness, balanceAfter, wasMaxWinCapped,
            uncappedPayout, maxPayout, createdAt.
            Raises urllib.error.HTTPError(402) on insufficient balance.

        Examples
        --------
        api.place_bet("dice",     wager_amount=50, target=81.91, direction="under")
        api.place_bet("limbo",    wager_amount=50, target=2)
        api.place_bet("coinflip", wager_amount=50, choice=1)       # Heads
        api.place_bet("plinko",   wager_amount=50, rows=8)
        api.place_bet("roll",     wager_amount=50, choices=[0,1,2,3])
        # hilo: see place_bet + hilo_action below
        """
        body: Dict = {
            "slug":        slug,
            "wagerAmount": str(wager_amount),
        }
        if target is not None:
            body["target"] = target
        if direction is not None:
            body["direction"] = direction
        if choice is not None:
            body["choice"] = choice
        if rows is not None:
            body["rows"] = rows
        if choices is not None:
            body["choices"] = choices
        return self._post(f"/api/archetype/{slug}/play", body=body)

    def hilo_action(self, round_id: str, action: str) -> Dict:
        """
        Play one step of an active HiLo round.  Requires ``auth_token``.

        VERIFIED endpoint: POST /api/archetype/hilo/action
        Call after place_bet("hilo", ...) returns state="OPEN".

        Parameters
        ----------
        round_id : str
            The ``roundId`` returned by place_bet("hilo", ...).
        action : str
            "higher" — bet next card rank is higher than current
            "lower"  — bet next card rank is lower than current
            "same"   — bet next card rank is the same (high-risk, ~16.66x)

        Returns
        -------
        dict
            roundId, state ("OPEN" to continue | "CLOSED" when done),
            action, card (index, rank, suit), outcome ("higher"|"lower"|"same"),
            correct (bool), currentMultiplier, payoutAmount, profit, won,
            balanceAfter, wasMaxWinCapped.
            When state="CLOSED": also includes serverSeedRevealed.

        Example
        -------
        # Start hilo round
        round_info = api.place_bet("hilo", wager_amount=50)
        # round_info contains: startCard, odds (higher/lower/same with multipliers)

        # Take action based on odds
        result = api.hilo_action(round_info["roundId"], "lower")
        if result["state"] == "OPEN":
            # still in round — can take another action or cashout
            result = api.hilo_action(round_info["roundId"], "higher")
        """
        return self._post("/api/archetype/hilo/action", body={
            "roundId": round_id,
            "action":  action,
        })

    # ── my bets (authenticated) ───────────────────────────────────────────────

    def get_my_bets(self, page: int = 1, filter_: str = "all") -> Dict:
        """
        Return the authenticated user's own bet history.

        Requires ``auth_token``.
        Returns: data.bets (list), data.count, data.pageCount, data.page.
        Each bet: id, gameId, gameName, wagerAmount, payoutAmount,
                  multiplier, currency, createdAt.

        Parameters
        ----------
        filter_ : str   "all" | "wins" | "losses"
        """
        return self._get("/api/me/bets", params={"page": page, "filter": filter_})

    # ── leaderboards (public) ─────────────────────────────────────────────────

    def get_leaderboard_top_games(
        self,
        window: str = "30d",
        limit: int = 20,
    ) -> Dict:
        """
        Return top games by betting volume.

        Parameters
        ----------
        window : str   "24h" | "7d" | "30d" | "all"

        Returns list of games with: rank, gameId, name, slug, archetype,
                creator, metrics (volumeUsdc, betCount, uniquePlayers, ngrUsdc).
        """
        return self._get("/api/leaderboard/top-games",
                         params={"window": window, "limit": limit})

    def get_leaderboard_top_creators(
        self,
        window: str = "30d",
        limit: int = 20,
    ) -> Dict:
        """
        Return top game creators by volume.

        Returns list with: rank, displayName, walletAddress, metrics
        (gamesPublished, windowVolumeUsdc, windowNgrUsdc, lifetimeBetCount).
        """
        return self._get("/api/leaderboard/top-creators",
                         params={"window": window, "limit": limit})

    def get_leaderboard_top_earners(self, limit: int = 20) -> Dict:
        """
        Return top credit earners on the platform.

        Returns list with: rank, displayName, walletTruncated,
        metrics (lifetimeCreditsEarned, packsOpened, totalSharesHeld, gamesOwned).
        """
        return self._get("/api/leaderboard/top-credit-earners",
                         params={"sort": "credits-earned", "limit": limit})

    # ── chat (authenticated) ──────────────────────────────────────────────────

    def get_chat_messages(
        self,
        channel_id: str = "general",
        limit: int = 50,
    ) -> Dict:
        """
        Return chat messages for a channel.

        Requires ``auth_token``.
        Returns: data.messages — list of {id, channelId, userId, displayName,
                 walletAddress, vipLevel, content, createdAt}.
        """
        return self._get("/api/chat/messages",
                         params={"channelId": channel_id, "limit": limit})

    # ── WINR Protocol analytics (gateway.winr.games) ─────────────────────────

    def get_token_prices(self) -> Any:
        """
        Fetch current USD token prices from the WINR analytics gateway.

        Uses gateway.winr.games (separate from main backend).
        Returns list of { symbol, price, ... }.
        """
        url = f"{WINR_GATEWAY_URL}/currency/get-last-prices"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json", "User-Agent": "justbet-sdk/0.1.0"
        })
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_protocol_stats(self) -> Any:
        """
        Fetch global protocol stats from gateway.winr.games.

        Returns dict with: profitShared, totalVolume, gameCount, etc.
        """
        url = f"{WINR_GATEWAY_URL}/statistic/get-stats"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json", "User-Agent": "justbet-sdk/0.1.0"
        })
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ── Privy auth helpers ────────────────────────────────────────────────────

    @staticmethod
    def request_otp(email: str) -> bool:
        """
        Step 1 of Privy login: send an OTP code to the given email.

        VERIFIED from Burp: POST auth.privy.io/api/v1/passwordless/init

        Parameters
        ----------
        email : str   The email address registered on just.bet.

        Returns
        -------
        bool   True if request succeeded (OTP email sent).
        """
        url  = f"{_PRIVY_BASE}/api/v1/passwordless/init"
        body = json.dumps({"email": email}).encode()
        req  = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type":  "application/json",
                "Accept":        "application/json",
                "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
                "Privy-App-Id":  PRIVY_APP_ID,
                "Privy-Client":  "react-auth:3.18.0",
                "Origin":        "https://www.just.bet",
                "Referer":       "https://www.just.bet/",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("success", False)

    @staticmethod
    def login_with_email(email: str, otp_code: str) -> "JustBetAPI":
        """
        Step 2 of Privy login: verify OTP and return an authenticated JustBetAPI.

        VERIFIED from Burp: POST auth.privy.io/api/v1/passwordless/authenticate
        Body: {"email": "...", "code": "606634", "mode": "login-or-sign-up"}
        Response: {"token": "eyJ...", "user": {...}}

        After obtaining the token, also calls POST /api/user/register to
        activate the session on the just.bet backend (verified from Burp).

        Parameters
        ----------
        email    : str   Email address.
        otp_code : str   6-digit OTP from the email.

        Returns
        -------
        JustBetAPI   Authenticated instance ready to call balance, place_bet, etc.

        Example
        -------
        JustBetAPI.request_otp("your@email.com")
        api = JustBetAPI.login_with_email("your@email.com", "123456")
        print(api.get_balance())
        """
        url  = f"{_PRIVY_BASE}/api/v1/passwordless/authenticate"
        body = json.dumps({
            "email": email,
            "code":  otp_code,
            "mode":  "login-or-sign-up",
        }).encode()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept":       "application/json",
                "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
                "Privy-App-Id": PRIVY_APP_ID,
                "Privy-Client": "react-auth:3.18.0",
                "Origin":       "https://www.just.bet",
                "Referer":      "https://www.just.bet/",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        token = data.get("token") or data.get("privy_access_token")
        if not token:
            raise ValueError(
                f"Privy login failed — no token in response. "
                f"Keys received: {list(data.keys())}"
            )

        # Activate session on just.bet backend (verified from Burp)
        api = JustBetAPI(auth_token=token)
        try:
            api._post("/api/user/register", body={})
            logger.info("just.bet session registered successfully")
        except Exception as exc:
            logger.debug("register call failed (non-fatal): %s", exc)

        logger.info("Logged in via Privy | email=%s", email)
        return api
