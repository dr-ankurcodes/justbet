"""
just.bet game ID registry.

VERIFIED from live Burp Suite traffic analysis of just.bet (June 2026).
Source: /api/games/new-releases, /api/games/most-popular, /api/games/trending
        and /ai/games/detail responses captured from the live site.

Each game has an internal UUID used by the just.bet backend API for:
  - GET /api/games/{game_id}/config  → min/max bet, top multiplier
  - GET /api/history/high-rollers?gameId={game_id}
  - Bet history records (bets reference these UUIDs)

Only the 13 original JustBet games are included here.
AI-created/creator games are not supported — their bet endpoints are
browser-only and require game-specific frontend logic.
"""

# ── Original JustBet game UUIDs (verified from Burp traffic) ──────────────────
# Format: slug → uuid

GAME_IDS: dict = {
    "coinflip":    "2d1815d3-d86a-45cd-8a02-96984ea5fada",
    "dice":        "5b55ea3a-2f90-4c7d-bf4f-18665fd4028e",
    "limbo":       "4b2e766d-768a-4c25-9169-b356eb6e978b",
    "plinko":      "dc48ab77-1288-4d4d-9f2a-cb21393135b8",
    "roll":        "e5b85122-816d-4455-b279-d025768b9e68",
    "keno":        "25ea8a28-ed04-47e0-9b5d-1d72e702e51b",
    "roulette":    "5a1f1b77-542a-4bf4-a52f-748ca5d1f426",
    "wheel":       "f2ba44bb-a393-414a-8a59-35d253572b6b",
    "hilo":        "a7ff9d78-4fca-485f-b386-ed8ea49a9fec",
    "holdem":      "0a254072-7807-4041-bead-29b55ee82704",
    "blackjack":   "a2dc0aa2-f902-469c-85e3-beaa63391440",
    "video_poker": "49e261a6-5754-4f59-973b-6d5d353a1c22",
    "baccarat":    "044ada6a-3a8a-473e-8283-fce756b5cc20",
}

# Reverse lookup: uuid → slug
GAME_ID_TO_SLUG: dict = {v: k for k, v in GAME_IDS.items()}

# All 13 original JustBet game slugs
ORIGINAL_GAMES = [
    "coinflip", "dice", "limbo", "plinko", "roll", "keno",
    "roulette", "wheel", "hilo", "holdem", "blackjack",
    "video_poker", "baccarat",
]

# Games with fully verified request/response (Burp-captured, June 2026)
VERIFIED_GAMES = ["dice", "limbo", "coinflip", "plinko", "roll", "hilo"]


def get_game_id(slug: str) -> str:
    """
    Return the backend UUID for a game slug.

    Parameters
    ----------
    slug : str
        e.g. "coinflip", "dice", "limbo", "wheel"

    Raises
    ------
    KeyError if slug not found.
    """
    game_id = GAME_IDS.get(slug.lower())
    if game_id is None:
        raise KeyError(
            f"Unknown game slug '{slug}'. "
            f"Known games: {ORIGINAL_GAMES}"
        )
    return game_id


def get_slug(game_id: str) -> str:
    """Return the slug for a given game UUID."""
    slug = GAME_ID_TO_SLUG.get(game_id)
    if slug is None:
        raise KeyError(f"Unknown game ID '{game_id}'.")
    return slug
