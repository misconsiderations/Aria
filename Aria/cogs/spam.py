from discord.ext import commands  # type: ignore
import discord  # type: ignore
import asyncio

class Spam(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="create_webhook_spam", help="Create webhooks and use them for ultra-fast custom message spam")
    @commands.is_owner()
    async def create_webhook_spam(self, ctx, amount: int, *, message: str):
        guild = ctx.guild
        if not guild:
            await ctx.send("Not in a server.")
            return

        tasks = []
        for channel in guild.text_channels:
            try:
                webhook = await channel.create_webhook(name="SpamWebhook")
                for _ in range(amount):
                    tasks.append(webhook.send(message, wait=True))
                tasks.append(webhook.delete())
            except Exception as e:
                print(f"Failed to create or use webhook in {channel.name}: {e}")

        await asyncio.gather(*tasks)
        await ctx.send("Ultra-fast custom message spam completed.")

async def setup(bot):
    await bot.add_cog(Spam(bot))