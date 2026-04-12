from discord.ext import commands  # type: ignore

class Owo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="owo", help="Simulates an owo interaction")
    async def owo(self, ctx):
        await ctx.send("OwO! You look amazing today!")

    @commands.command(name="uwu", help="Simulates an uwu interaction")
    async def uwu(self, ctx):
        await ctx.send("UwU! You're so adorable!")

async def setup(bot):
    await bot.add_cog(Owo(bot))