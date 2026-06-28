"""
Configuration and verified address registry for just.bet (WINR Protocol).

All values verified from live Burp Suite traffic analysis, June 2026.
"""

# ── Verified token addresses (Arbitrum One, chain ID 42161) ──────────────────

TOKENS = {
    # Native USDC — primary wagering token on just.bet
    "USDC":   "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    # Bridged USDC.e (older)
    "USDC.e": "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8",
    # Wrapped Ether
    "WETH":   "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
    # WINR governance/reward token — primary in-platform currency
    "WINR":   "0xD77B108d4f6cefaa0Cae9506A934e825BEccA46E",
    # vWINR (vested WINR)
    "vWINR":  "0xD75a51364440dAF83B78B9888D2b8F28eaC0D280",
}

# ── Verified protocol contract addresses (Arbitrum One) ──────────────────────

PROTOCOL_ADDRESSES = {
    # Cashier/Escrow — deposit USDC/WINR here to fund your just.bet balance
    "cashier":     "0x4685AcE4e80144E2Fd23380Cf76bd36e47a838Fb",
    # House bankroll pool
    "bankroll":    "0xFFBC24fbe694b15093d8233476CD27ED9e9C778C",
    # WINR staking
    "staking":     "0x5eD22F7693fea5A0B45dB31771aa94E941b6df8a",
    # WINR token
    "winr_token":  "0xD77B108d4f6cefaa0Cae9506A934e825BEccA46E",
    # vWINR token
    "vwinr_token": "0xD75a51364440dAF83B78B9888D2b8F28eaC0D280",
}

# ── Network ───────────────────────────────────────────────────────────────────

ARBITRUM_ONE_CHAIN_ID = 42161

# ── Verified API URLs ─────────────────────────────────────────────────────────

# Primary just.bet backend — games, bets, balances, history
JUSTBET_API_BASE_URL = "https://jb-development-eqoyn.ondigitalocean.app"

# Legacy WINR Protocol analytics
WINR_GATEWAY_URL = "https://gateway.winr.games"

# Privy authentication app ID used by just.bet
PRIVY_APP_ID = "cmnd3ngp901ty0clb9rknxcxi"
