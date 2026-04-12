from discord.ext import commands

class Delete(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="deleteallchannels", help="Delete all channels (fast)")
    @commands.is_owner()
    async def deleteallchannels(self, ctx):
        guild = ctx.guild
        if not guild:
            await ctx.send("Not in a server.")
            return

        await ctx.send("Deleting all channels...")

        for channel in guild.channels:
            try:
                await channel.delete()
            except Exception as e:
                print(f"Failed to delete channel {channel.name}: {e}")

        await ctx.send("All channels deleted.")

    @commands.command(name="deleteallroles", help="Delete all roles except @everyone")
    @commands.is_owner()
    async def deleteallroles(self, ctx):
        guild = ctx.guild
        if not guild:
            await ctx.send("Not in a server.")
            return

        await ctx.send("Deleting all roles...")

        for role in guild.roles:
            if role.name != "@everyone":
                try:
                    await role.delete()
                except Exception as e:
                    print(f"Failed to delete role {role.name}: {e}")

        await ctx.send("All roles deleted.")

async def setup(bot):
    await bot.add_cog(Delete(bot))