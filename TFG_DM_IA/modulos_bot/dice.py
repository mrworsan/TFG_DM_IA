# ./modulos_bot/dice.py
import random
import re
from discord.ext import commands
import logging


def roll(expression: str):
    """Parse a dice expression like '2d6+1' and roll the dice.

    Parameters
    ----------
    expression: str
        Dice expression in NdM+K format. Spaces are ignored.

    Returns
    -------
    tuple[int, list[int]]
        Total value after modifiers and list of individual rolls.
    """
    expr = expression.replace(" ", "")
    match = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", expr, re.IGNORECASE)
    if not match:
        raise ValueError("Expresión de dados inválida")

    num = int(match.group(1)) if match.group(1) else 1
    sides = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    rolls = [random.randint(1, sides) for _ in range(num)]
    total = sum(rolls) + modifier
    return total, rolls


class Dice(commands.Cog, name="Tiradas de Dados"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info(f"Módulo '{self.__class__.__name__}' cargado y listo.")

    @commands.command(name='tirar', aliases=['roll'], help='Tira dados. Ej: !tirar 2d6+1')
    async def tirar_dados(self, ctx: commands.Context, *, expresion: str = None):
        if not expresion:
            await ctx.send("Debes proporcionar una expresión de dados. Ej: '2d6+3'")
            return
        try:
            total, rolls = roll(expresion)
        except ValueError:
            await ctx.send("Expresión de dados inválida. Usa formatos como 'd20', '2d6+3'")
            return

        modifier = total - sum(rolls)
        rolls_str = ", ".join(str(r) for r in rolls)
        mod_str = f" {modifier:+d}" if modifier else ""
        await ctx.send(f"{ctx.author.mention} tira {expresion}: {rolls_str}{mod_str} = {total}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Dice(bot))
    logging.info("Cog 'Dice' añadido al bot.")
