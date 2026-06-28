"""
justbet_sdk — Python SDK for just.bet (WINR Protocol).

Lets an AI agent authenticate, read game data, and place bets on just.bet
using the verified backend API (https://jb-development-eqoyn.ondigitalocean.app).

No external dependencies. Pure Python standard library.

Quick start
-----------
    from justbet_sdk import JustBetAPI, GAME_IDS, get_game_id

    # Login (human step — save token for reuse)
    JustBetAPI.request_otp("user@email.com")
    api = JustBetAPI.login_with_email("user@email.com", "123456")

    # Check balance
    print(api.get_balance())

    # Place a bet
    result = api.place_bet("dice", wager_amount=50, target=81.91, direction="under")
    print(result)
"""

from justbet_sdk.api import JustBetAPI
from justbet_sdk.game_ids import (
    GAME_IDS,
    GAME_ID_TO_SLUG,
    ORIGINAL_GAMES,
    VERIFIED_GAMES,
    get_game_id,
    get_slug,
)
from justbet_sdk.config import (
    TOKENS,
    PROTOCOL_ADDRESSES,
    ARBITRUM_ONE_CHAIN_ID,
    JUSTBET_API_BASE_URL,
    WINR_GATEWAY_URL,
    PRIVY_APP_ID,
)
from justbet_sdk.exceptions import JustBetError

__all__ = [
    # Main client
    "JustBetAPI",
    # Game IDs
    "GAME_IDS",
    "GAME_ID_TO_SLUG",
    "ORIGINAL_GAMES",
    "VERIFIED_GAMES",
    "get_game_id",
    "get_slug",
    # Addresses / config
    "TOKENS",
    "PROTOCOL_ADDRESSES",
    "ARBITRUM_ONE_CHAIN_ID",
    "JUSTBET_API_BASE_URL",
    "WINR_GATEWAY_URL",
    "PRIVY_APP_ID",
    # Exception
    "JustBetError",
]

__version__ = "0.1.0"
