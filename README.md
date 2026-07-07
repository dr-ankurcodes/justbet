
Unofficial sdk wrapper for just.bet, mainly for AI agents (see PROMPT.md). See AGENTS.md and example_agent.py for usage.
auto_bet_*.py is for manual infinite cycle (for dice roll, hilo, video_poker respectively) on just.bet (modify config via variables on Top).
refresh_token.py - refreshes access token in token.txt from refresh token in token.txt
*auto_bet_*.py files uses token.txt but SDK uses /tmp/justbet_token.txt for token access. auto_bet_*.py files are independent and separate from SDK and are for individual & continuous autoplay specific games - not for AI agents.
In SDK Currently Only 7 games (dice, limbo, hilo, coinflip, plinko, roll, video_poker) playable out of 15 games publised by justbet account on just.bet

**TO BE REPLACED BEFORE PROCEEDING**:
1. JUSTBET_DIRECTORY_PATH - absolute path of this directory - in AGENTS.md, PROMPT.md, auto_bet_dice.py, auto_bet_video_poker.py
2. TEMPORARY_FOLDER - a temporary folder (e.g. /tmp/ for linux) to save tokens. Can be your working directory too - in AGENTS.md
3. YOUR_EMAIL_HERE - your email, account on just.bet - in PROMPT.md

**Try at your own risk.**  
**I will not be responsible if you loose your money. Play safe. (House Edge is a real thing anyways.)**  
**This is an unofficial SDK and for educational purpose only. I will not be responsible for any bug in the code.** 
