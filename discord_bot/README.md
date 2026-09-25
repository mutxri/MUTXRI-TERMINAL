# MUTXRI TERMINAL Discord bot

A free Discord bot that answers in your server with the terminal's live data
(same `static_data/` JSON the site serves). Commands: `!quote`, `!f`, `!gains`,
`!losers`, `!idx`, `!digest`, `!help`.

## Setup (one time, ~3 min)

### 1. Create the bot application
1. Go to https://discord.com/developers/applications → **New Application** → name it **MUTXRI TERMINAL**.
2. Left sidebar → **Bot** → **Reset Token** → **Copy** the token.

### 2. Give the bot read-message permission
3. Same **Bot** page → scroll to **Privileged Gateway Intents** → turn ON **Message Content Intent** → **Save Changes**.

### 3. Put the token in a local file (never in chat)
4. In this folder, copy `.env.example` to `.env` and paste the token:
   ```
   DISCORD_TOKEN=paste_your_token_here
   ```

### 4. Invite the bot to your server
5. Left sidebar → **OAuth2** → **URL Generator**:
   - Scopes: tick **bot**
   - Bot permissions: **Send Messages**, **Embed Links**, **Read Message History**
6. Copy the generated URL, open it, and pick your server → **Authorize**.

### 5. Run it
```bash
cd D:\mutxri-terminal\discord_bot
python -m pip install -r requirements.txt
python bot.py
```
Keep the window open — the bot runs as long as that process is alive.

## Notes
- Data auto-refreshes: the bot re-reads a file whenever its timestamp changes,
  so it picks up `refresh_all.py` / scheduled refreshes without a restart.
- If a ticker returns nothing, use its exchange ticker (e.g. `4SI.JO` for JSE,
  `INFI` for EGX) — the bot matches across all four listings.
