"""
example_agent.py — Demonstrates the just.bet SDK for an AI agent.

HOW TO RUN
──────────
  pip install -e .
  python example_agent.py

For authenticated endpoints (balance, bet placement):
  python example_agent.py --email user@email.com --otp 123456
"""

import argparse
import logging
import urllib.error

from justbet_sdk import (
    JustBetAPI, GAME_IDS, get_game_id,
    JUSTBET_API_BASE_URL, ORIGINAL_GAMES, VERIFIED_GAMES,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def demo_public(api: JustBetAPI) -> None:
    """Public endpoints — no login required."""

    log.info("=== Game Configs (verified games) ===")
    for slug in VERIFIED_GAMES:
        try:
            data = api.get_game_config(get_game_id(slug)).get("data", {})
            log.info("  %-12s  min=%-6s  max=%-8s  topMult=%s",
                     slug, data.get("minBet"), data.get("maxBet"),
                     data.get("topMultiplier", {}).get("multiplier"))
        except Exception as e:
            log.warning("  %-12s  error: %s", slug, e)

    log.info("\n=== High Rollers (all games) ===")
    try:
        bets = api.get_high_rollers(per_page=5).get("data", {}).get("bets", [])
        for b in bets[:3]:
            log.info("  %-12s  wager=%-8s  mult=%.2fx  wallet=%s",
                     b.get("gameName", "")[:12], b.get("wagerAmount"),
                     b.get("multiplier", 0), b.get("walletTruncated"))
    except Exception as e:
        log.warning("  error: %s", e)

    log.info("\n=== Lucky Winners (highest multipliers) ===")
    try:
        bets = api.get_lucky_winners(per_page=3).get("data", {}).get("bets", [])
        for b in bets[:3]:
            log.info("  %-12s  wager=%-6s  mult=%.1fx  payout=%s",
                     b.get("gameName", "")[:12], b.get("wagerAmount"),
                     b.get("multiplier", 0), b.get("payoutAmount"))
    except Exception as e:
        log.warning("  error: %s", e)

    log.info("\n=== Top Games (30d) ===")
    try:
        games = api.get_leaderboard_top_games(window="30d", limit=5).get("data", {}).get("games", [])
        for g in games[:3]:
            log.info("  #%-2d %-25s  volume=%s  bets=%s",
                     g.get("rank"), g.get("name"),
                     g.get("metrics", {}).get("volumeUsdc"),
                     g.get("metrics", {}).get("betCount"))
    except Exception as e:
        log.warning("  error: %s", e)


def demo_authenticated(api: JustBetAPI) -> None:
    """Authenticated endpoints — requires login."""

    log.info("\n=== Balance ===")
    bal = api.get_balance()
    log.info("  balance=%s  usdc=%s  winr=%s",
             bal.get("balance"), bal.get("usdc"), bal.get("winr"))

    log.info("\n=== Profile ===")
    me = api.get_user_me().get("data", {})
    log.info("  wallet=%s  vipLevel=%s  totalBets=%s",
             me.get("walletAddress"), me.get("vipLevel"), me.get("totalBets"))

    log.info("\n=== Daily Rewards ===")
    dr = api.get_daily_rewards()
    log.info("  streakDays=%s  claimable=%s  nextDay=%s",
             dr.get("streakDays"), dr.get("isClaimableNow"), dr.get("nextClaimDay"))

    log.info("\n=== Place Bets (verified games) ===")
    bets = [
        ("dice",     {"wager_amount": 50, "target": 50.0, "direction": "under"}),
        ("limbo",    {"wager_amount": 50, "target": 2}),
        ("coinflip", {"wager_amount": 50, "choice": 1}),
        ("plinko",   {"wager_amount": 50, "rows": 8}),
        ("roll",     {"wager_amount": 50, "choices": [0, 1, 2, 3]}),
    ]
    for slug, kwargs in bets:
        try:
            result = api.place_bet(slug, **kwargs)
            r = result.get("result", {})
            log.info("  %-8s  won=%-5s  mult=%.2fx  payout=%s",
                     slug, r.get("won"), result.get("multiplier", 0),
                     result.get("payoutAmount"))
        except urllib.error.HTTPError as e:
            if e.code == 402:
                log.warning("  %-8s  Insufficient balance (top up first)", slug)
            else:
                log.warning("  %-8s  HTTP %s: %s", slug, e.code, e)
        except Exception as e:
            log.warning("  %-8s  error: %s", slug, e)

    log.info("\n=== HiLo Demo ===")
    try:
        round_info = api.place_bet("hilo", wager_amount=50)
        sc = round_info.get("startCard", {})
        odds = round_info.get("odds", {})
        log.info("  startCard rank=%s suit=%s | odds: higher=%.2fx lower=%.2fx same=%.2fx",
                 sc.get("rank"), sc.get("suit"),
                 odds.get("higher", {}).get("multiplier", 0),
                 odds.get("lower", {}).get("multiplier", 0),
                 odds.get("same", {}).get("multiplier", 0))
        result = api.hilo_action(round_info["roundId"], "lower")
        log.info("  action=lower  outcome=%s  correct=%s  won=%s  payout=%s",
                 result.get("outcome"), result.get("correct"),
                 result.get("won"), result.get("payoutAmount"))
    except urllib.error.HTTPError as e:
        if e.code == 402:
            log.warning("  hilo  Insufficient balance (top up first)")
        else:
            log.warning("  hilo  HTTP %s: %s", e.code, e)
    except Exception as e:
        log.warning("  hilo  error: %s", e)

    log.info("\n=== Recent Bets ===")
    my_bets = api.get_my_bets(page=1).get("data", {}).get("bets", [])
    if my_bets:
        for b in my_bets[:3]:
            log.info("  %-12s  wager=%s  payout=%s  mult=%.2fx",
                     b.get("gameName", "")[:12], b.get("wagerAmount"),
                     b.get("payoutAmount"), b.get("multiplier", 0))
    else:
        log.info("  (no bets yet)")


def main() -> None:
    parser = argparse.ArgumentParser(description="just.bet SDK demo")
    parser.add_argument("--email", help="Email for Privy login")
    parser.add_argument("--otp",   help="OTP code from email")
    parser.add_argument("--request-otp", action="store_true",
                        help="Request an OTP for --email (check your inbox, then re-run with --otp)")
    args = parser.parse_args()

    log.info("just.bet SDK | backend=%s", JUSTBET_API_BASE_URL)
    log.info("Original games (%d): %s", len(ORIGINAL_GAMES), ORIGINAL_GAMES)
    log.info("Verified for betting (%d): %s", len(VERIFIED_GAMES), VERIFIED_GAMES)

    # ── Request OTP only ─────────────────────────────────────────────────────
    if args.request_otp:
        if not args.email:
            log.error("--email required with --request-otp")
            return
        ok = JustBetAPI.request_otp(args.email)
        log.info("OTP sent: %s — check your inbox, then run with --email and --otp", ok)
        return

    # ── Public demo (no auth) ─────────────────────────────────────────────────
    api = JustBetAPI()
    demo_public(api)

    # ── Authenticated demo ────────────────────────────────────────────────────
    if args.email and args.otp:
        log.info("\nLogging in as %s ...", args.email)
        api = JustBetAPI.login_with_email(args.email, args.otp)
        demo_authenticated(api)
    else:
        log.info("\n[Authenticated demo skipped — pass --email and --otp to enable]")
        log.info("[To get an OTP: python example_agent.py --request-otp --email user@example.com]")


if __name__ == "__main__":
    main()
