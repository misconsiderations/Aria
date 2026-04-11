import discord
from discord.ext import commands
import logging
import time
from utils.general import format_message, quote_block

logger = logging.getLogger(__name__)

class afk_system(commands.Cog):
    """Handle AFK status and auto-responses"""
    def __init__(self, bot):
        self.bot = bot
        self.afk = False
        self.afk_message = "I'm currently AFK."
        self.last_afk_message = {} 
        self.cooldown = 60 
        self.afk_since = None

    def reset_afk(self):
        self.afk = False
        self.afk_message = "I'm currently AFK."
        self.afk_since = None
        self.last_afk_message.clear()

    @commands.command(aliases=['away'])
    async def afk(self, ctx, *, message: str = None):
        try:
            try: await ctx.message.delete()
            except: pass
            self.afk = True
            self.afk_since = time.time()
            if message: self.afk_message = message
            await ctx.send(format_message(f"AFK enabled: {self.afk_message}"))
        except Exception as e:
            logger.error(f"Error in afk command: {e}")

    def get_time_message(self):
        if not self.afk_since: return ""
        elapsed = int(time.time() - self.afk_since)
        seconds = elapsed % 60
        return f"`AFK for {seconds}s`"

    async def _handle_message(self, message):
        if not message.author.bot and message.author.id == self.bot.user.id:
            if self.afk and not message.content.startswith(f"{self.bot.command_prefix}afk"):
                self.reset_afk()

    async def setup(bot):
        await bot.add_cog(afk_system(bot))
