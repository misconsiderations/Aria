import asyncio
import base64
import datetime
import random
import os
import ast
import operator as op
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import Config


def _get_bot_token() -> str:
    # Prefer env var so tokens are not committed to config files.
    env_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if env_token:
        return env_token

    cfg = Config()
    return str(cfg.get("discord_bot_token", "") or "").strip()


def _get_sync_guild_id() -> Optional[int]:
    raw = os.getenv("DISCORD_SLASH_GUILD_ID", "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        return None
    return int(raw)


def _get_hide_replies_default() -> bool:
    env_raw = os.getenv("DISCORD_SLASH_HIDE_REPLIES", "").strip().lower()
    if env_raw in {"1", "true", "yes", "on"}:
        return True
    if env_raw in {"0", "false", "no", "off"}:
        return False

    cfg = Config()
    return bool(cfg.get("slash_hide_replies", False))


class AriaSlashBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True

        super().__init__(command_prefix="!", intents=intents)
        self.synced_once = False
        self.hide_replies_default = _get_hide_replies_default()

    async def _respond(
        self,
        interaction: discord.Interaction,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        hidden: Optional[bool] = None,
    ) -> None:
        is_hidden = self.hide_replies_default if hidden is None else bool(hidden)
        await interaction.response.send_message(content=content, embed=embed, ephemeral=is_hidden)

    async def setup_hook(self) -> None:
        # Define slash commands at startup.

        @self.tree.command(name="ping", description="Check slash bot latency")
        async def ping(interaction: discord.Interaction) -> None:
            ms = round(self.latency * 1000)
            await self._respond(interaction, f"Pong: {ms}ms")

        @self.tree.command(name="help", description="Show available slash commands")
        async def help_cmd(interaction: discord.Interaction) -> None:
            lines = [
                "/ping - latency check",
                "/mock <text> - alternating-case text",
                "/clap <text> - clap separators",
                "/coinflip - heads or tails",
                "/rng <min> <max> - random number in range",
                "/rate <text> - rate text 1-10",
                "/userinfo [user] - show user information",
                "/serverinfo - show server details",
                "/avatar [user] - show avatar URL",
                "/say <text> [hidden] - bot repeats your text",
                "/reply <text> [hidden] - quick hidden/public reply",
                "/choose <a,b,c> - pick one option",
                "/roll [sides] - roll dice",
                "/timestamp [unix] - format Discord timestamp",
                "/b64encode <text> - base64 encode",
                "/b64decode <text> - base64 decode",
                "/reverse <text> - reverse text",
                "/upper <text> - uppercase text",
                "/lower <text> - lowercase text",
                "/length <text> - character/word count",
                "/wordcount <text> - word count only",
                "/calc <expr> - safe calculator",
                "/charinfo <text> - Unicode code points",
                "Works in DMs and servers (serverinfo is guild-only)",
            ]
            await self._respond(interaction, "\n".join(lines), hidden=True)

        @self.tree.command(name="mock", description="Convert text to alternating case")
        @app_commands.describe(text="Text to transform")
        async def mock_cmd(interaction: discord.Interaction, text: str) -> None:
            out = []
            upper = False
            for ch in text:
                if ch.isalpha():
                    out.append(ch.upper() if upper else ch.lower())
                    upper = not upper
                else:
                    out.append(ch)
            await self._respond(interaction, "".join(out))

        @self.tree.command(name="clap", description="Insert clap emoji between words")
        @app_commands.describe(text="Text to transform")
        async def clap_cmd(interaction: discord.Interaction, text: str) -> None:
            words = [w for w in text.split() if w]
            if not words:
                await self._respond(interaction, "Provide text to clap.", hidden=True)
                return
            await self._respond(interaction, " 👏 ".join(words))

        @self.tree.command(name="coinflip", description="Flip a coin")
        async def coinflip_cmd(interaction: discord.Interaction) -> None:
            await self._respond(interaction, random.choice(["Heads", "Tails"]))

        @self.tree.command(name="rng", description="Random number between min and max")
        @app_commands.describe(minimum="Minimum value", maximum="Maximum value")
        async def rng_cmd(interaction: discord.Interaction, minimum: int, maximum: int) -> None:
            lo = min(minimum, maximum)
            hi = max(minimum, maximum)
            if hi - lo > 1_000_000:
                await self._respond(interaction, "Range too large (max span: 1,000,000).", hidden=True)
                return
            await self._respond(interaction, str(random.randint(lo, hi)))

        @self.tree.command(name="rate", description="Rate something from 1 to 10")
        @app_commands.describe(text="Thing to rate")
        async def rate_cmd(interaction: discord.Interaction, text: str) -> None:
            score = random.randint(1, 10)
            await self._respond(interaction, f"{text} -> **{score}/10**")

        @self.tree.command(name="userinfo", description="Show info about a Discord user")
        @app_commands.describe(user="User to inspect (defaults to you)")
        async def userinfo(interaction: discord.Interaction, user: Optional[discord.User] = None) -> None:
            target = user or interaction.user
            embed = discord.Embed(title="User Info", color=discord.Color.blurple())
            embed.add_field(name="Tag", value=str(target), inline=True)
            embed.add_field(name="ID", value=str(target.id), inline=True)
            joined_at = getattr(target, "joined_at", None)
            if joined_at:
                embed.add_field(name="Joined", value=discord.utils.format_dt(joined_at, style="R"), inline=True)
            created_at = getattr(target, "created_at", None)
            if created_at:
                embed.add_field(name="Created", value=discord.utils.format_dt(created_at, style="R"), inline=True)
            avatar = getattr(target, "display_avatar", None)
            if avatar:
                embed.set_thumbnail(url=avatar.url)
            await self._respond(interaction, embed=embed)

        @self.tree.command(name="serverinfo", description="Show info about the current server")
        async def serverinfo(interaction: discord.Interaction) -> None:
            guild = interaction.guild
            if guild is None:
                await self._respond(interaction, "This command only works in servers.", hidden=True)
                return

            embed = discord.Embed(title="Server Info", color=discord.Color.green())
            embed.add_field(name="Name", value=guild.name, inline=True)
            embed.add_field(name="ID", value=str(guild.id), inline=True)
            embed.add_field(name="Members", value=str(guild.member_count or 0), inline=True)
            if guild.created_at:
                embed.add_field(name="Created", value=discord.utils.format_dt(guild.created_at, style="R"), inline=True)
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            await self._respond(interaction, embed=embed)

        @self.tree.command(name="avatar", description="Get a user avatar URL")
        @app_commands.describe(user="User to inspect (defaults to you)")
        async def avatar(interaction: discord.Interaction, user: Optional[discord.User] = None) -> None:
            target = user or interaction.user
            avatar = getattr(target, "display_avatar", None)
            if not avatar:
                await self._respond(interaction, "No avatar found.", hidden=True)
                return
            await self._respond(interaction, avatar.url)

        @self.tree.command(name="appmode", description="Explain how this app works with user installs")
        async def appmode(interaction: discord.Interaction) -> None:
            await self._respond(
                interaction,
                "This app runs commands through the bot application. "
                "It does not execute as your personal user account.",
                hidden=True,
            )

        @self.tree.command(name="say", description="Make the bot send a message")
        @app_commands.describe(text="Message text", hidden="Hide this reply from others")
        async def say(interaction: discord.Interaction, text: str, hidden: Optional[bool] = None) -> None:
            await self._respond(interaction, text, hidden=hidden)

        @self.tree.command(name="reply", description="Reply quickly with optional hidden visibility")
        @app_commands.describe(text="Reply text", hidden="Hide this reply from others")
        async def reply(interaction: discord.Interaction, text: str, hidden: Optional[bool] = None) -> None:
            await self._respond(interaction, text, hidden=hidden)

        @self.tree.command(name="choose", description="Choose one option from a comma-separated list")
        @app_commands.describe(options="Comma-separated options, e.g. red, blue, green")
        async def choose(interaction: discord.Interaction, options: str) -> None:
            items = [x.strip() for x in options.split(",") if x.strip()]
            if len(items) < 2:
                await self._respond(interaction, "Provide at least 2 options separated by commas.", hidden=True)
                return
            await self._respond(interaction, f"I choose: **{random.choice(items)}**")

        @self.tree.command(name="roll", description="Roll a random number")
        @app_commands.describe(sides="Number of sides (default 6, max 100000)")
        async def roll(interaction: discord.Interaction, sides: Optional[int] = 6) -> None:
            s = int(sides or 6)
            if s < 2 or s > 100000:
                await self._respond(interaction, "Sides must be between 2 and 100000.", hidden=True)
                return
            await self._respond(interaction, f"Rolled **{random.randint(1, s)}** (1-{s})")

        @self.tree.command(name="timestamp", description="Create a Discord timestamp from unix seconds")
        @app_commands.describe(unix="Unix seconds (optional, defaults to now)", style="t, T, d, D, f, F, R")
        async def timestamp(interaction: discord.Interaction, unix: Optional[int] = None, style: Optional[str] = "f") -> None:
            ts = int(unix if unix is not None else datetime.datetime.now(datetime.UTC).timestamp())
            st = (style or "f").strip()
            allowed = {"t", "T", "d", "D", "f", "F", "R"}
            if st not in allowed:
                st = "f"
            await self._respond(interaction, f"`<t:{ts}:{st}>` -> <t:{ts}:{st}>")

        @self.tree.command(name="b64encode", description="Base64 encode text")
        @app_commands.describe(text="Text to encode")
        async def b64encode_cmd(interaction: discord.Interaction, text: str) -> None:
            encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
            await self._respond(interaction, encoded)

        @self.tree.command(name="b64decode", description="Base64 decode text")
        @app_commands.describe(text="Base64 text to decode")
        async def b64decode_cmd(interaction: discord.Interaction, text: str) -> None:
            try:
                decoded = base64.b64decode(text.encode("ascii"), validate=True).decode("utf-8", errors="replace")
                await self._respond(interaction, decoded)
            except Exception:
                await self._respond(interaction, "Invalid base64 input.", hidden=True)

        @self.tree.command(name="reverse", description="Reverse text")
        @app_commands.describe(text="Text to reverse")
        async def reverse_cmd(interaction: discord.Interaction, text: str) -> None:
            await self._respond(interaction, text[::-1])

        @self.tree.command(name="upper", description="Convert text to uppercase")
        @app_commands.describe(text="Text to convert")
        async def upper_cmd(interaction: discord.Interaction, text: str) -> None:
            await self._respond(interaction, text.upper())

        @self.tree.command(name="lower", description="Convert text to lowercase")
        @app_commands.describe(text="Text to convert")
        async def lower_cmd(interaction: discord.Interaction, text: str) -> None:
            await self._respond(interaction, text.lower())

        @self.tree.command(name="length", description="Count characters and words")
        @app_commands.describe(text="Text to measure")
        async def length_cmd(interaction: discord.Interaction, text: str) -> None:
            chars = len(text)
            words = len([w for w in text.split() if w])
            await self._respond(interaction, f"Characters: **{chars}** | Words: **{words}**")

        @self.tree.command(name="wordcount", description="Count words only")
        @app_commands.describe(text="Text to count")
        async def wordcount_cmd(interaction: discord.Interaction, text: str) -> None:
            words = len([w for w in text.split() if w])
            await self._respond(interaction, f"Words: **{words}**")

        @self.tree.command(name="charinfo", description="Show Unicode codepoint info for text")
        @app_commands.describe(text="Text to inspect")
        async def charinfo_cmd(interaction: discord.Interaction, text: str) -> None:
            sample = text[:25]
            lines = [f"`{c}` U+{ord(c):04X}" for c in sample]
            if len(text) > 25:
                lines.append("...")
            await self._respond(interaction, "\n".join(lines), hidden=True)

        _ops = {
            ast.Add: op.add,
            ast.Sub: op.sub,
            ast.Mult: op.mul,
            ast.Div: op.truediv,
            ast.FloorDiv: op.floordiv,
            ast.Mod: op.mod,
            ast.Pow: op.pow,
            ast.USub: op.neg,
            ast.UAdd: op.pos,
        }

        def _eval_expr(expr: str):
            def _eval(node):
                if isinstance(node, ast.Num):
                    return node.n
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                    return node.value
                if isinstance(node, ast.BinOp):
                    fn = _ops.get(type(node.op))
                    if fn is None:
                        raise ValueError("unsupported operator")
                    return fn(_eval(node.left), _eval(node.right))
                if isinstance(node, ast.UnaryOp):
                    fn = _ops.get(type(node.op))
                    if fn is None:
                        raise ValueError("unsupported operator")
                    return fn(_eval(node.operand))
                raise ValueError("unsupported expression")

            tree = ast.parse(expr, mode="eval")
            return _eval(tree.body)

        @self.tree.command(name="calc", description="Evaluate a safe math expression")
        @app_commands.describe(expr="Example: (2+5)*3/7")
        async def calc_cmd(interaction: discord.Interaction, expr: str) -> None:
            if len(expr) > 120:
                await self._respond(interaction, "Expression too long.", hidden=True)
                return
            try:
                result = _eval_expr(expr)
            except Exception:
                await self._respond(interaction, "Invalid expression.", hidden=True)
                return
            await self._respond(interaction, f"{expr} = **{result}**")

    async def on_ready(self) -> None:
        if self.user is None:
            return

        if self.synced_once:
            return

        sync_guild_id = _get_sync_guild_id()
        try:
            if sync_guild_id:
                guild_obj = discord.Object(id=sync_guild_id)
                self.tree.copy_global_to(guild=guild_obj)
                synced = await self.tree.sync(guild=guild_obj)
                print(
                    f"[SlashBot] Logged in as {self.user} | Synced {len(synced)} guild commands to {sync_guild_id}"
                    f" | hidden-default={str(self.hide_replies_default).lower()}"
                )
            else:
                synced = await self.tree.sync()
                print(
                    f"[SlashBot] Logged in as {self.user} | Synced {len(synced)} global commands"
                    f" | hidden-default={str(self.hide_replies_default).lower()}"
                )
            self.synced_once = True
        except Exception as exc:
            print(f"[SlashBot] Sync failed: {exc}")


async def _run() -> None:
    token = _get_bot_token()
    if not token:
        raise RuntimeError(
            "No bot token found. Set DISCORD_BOT_TOKEN or add discord_bot_token to config.json"
        )

    bot = AriaSlashBot()
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
