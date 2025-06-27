import discord
from discord.ext import commands

class ComandoAyuda(commands.Cog, name="Ayuda"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='help', aliases=['ayuda'], help='Muestra todos los comandos disponibles y su descripción.')
    async def help_cmd(self, ctx: commands.Context):
        prefix = self.bot.command_prefix if isinstance(self.bot.command_prefix, str) else '!'
        embed = discord.Embed(title="Comandos disponibles", color=discord.Color.gold())
        for command in sorted(self.bot.commands, key=lambda c: c.name):
            if command.hidden:
                continue
            name = f"{prefix}{command.name}"
            if command.aliases:
                aliases = ', '.join(command.aliases)
                name += f" ({aliases})"
            description = command.help or 'Sin descripción'
            embed.add_field(name=name, value=description, inline=False)
        await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(ComandoAyuda(bot))


