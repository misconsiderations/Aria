# Real Slash Commands Setup

This adds true Discord application slash commands through a normal Discord bot account.

## Behavior (Important)
- Users invoke commands from their own Discord context (server install or user install).
- Responses come from your bot application, not from the user's personal account token.
- This is the expected and valid Discord model for slash commands.

## 1) Create a bot application
1. Open Discord Developer Portal.
2. Create an application.
3. Open the Bot tab and click "Add Bot".
4. Copy the bot token.

## 2) Invite bot with slash scope
Use OAuth2 URL Generator with scopes:
- `bot`
- `applications.commands`

Grant permissions your commands need (for current commands, Send Messages + Embed Links is enough).

For user-install (private/user context), use OAuth2 with:
- `applications.commands`
- `integration_type=1`

You can generate links from Aria using:
- `;signup` (both links)
- `;signup user` (user-install link)

## 3) Provide token
Use one of these options:
- Environment variable (recommended):
  - `export DISCORD_BOT_TOKEN="YOUR_BOT_TOKEN"`
- Or set `discord_bot_token` in `config.json`.

Optional for instant command updates in one test guild:
- `export DISCORD_SLASH_GUILD_ID="YOUR_GUILD_ID"`

If `DISCORD_SLASH_GUILD_ID` is set, commands sync to that guild quickly.
If not set, global sync is used (can take longer to appear).

## 4) Run the slash bot
From the `Aria` folder:

```bash
python3 slash_bot.py
```

## Included slash commands
- `/ping`
- `/help`
- `/userinfo`
- `/serverinfo`
- `/avatar`
- `/say`
- `/reply`
- `/choose`
- `/roll`
- `/timestamp`
- `/b64encode`
- `/b64decode`
- `/reverse`
- `/upper`
- `/lower`
- `/length`
- `/mock`
- `/clap`
- `/coinflip`
- `/rng`
- `/rate`
- `/wordcount`
- `/charinfo`
- `/calc`

## Notes
- This is separate from your selfbot flow in `main.py`.
- Real slash commands require a bot account. A user account/selfbot cannot register user-facing slash commands for everyone.
- Hidden replies can be managed via `;slashbot hidereplies on|off|status`.
