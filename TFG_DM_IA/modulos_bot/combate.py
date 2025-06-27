import discord
from discord.ext import commands
import logging
import asyncio
import random
import re

try:
    import dice  # type: ignore
except Exception:  # pragma: no cover - fallback when library missing
    dice = None


def roll(expression: str) -> int:
    """Roll dice using `dice` library if available, else a simple parser."""
    if dice:
        try:
            return dice.roll(expression)
        except Exception as exc:  # pragma: no cover - if expression invalid
            logging.error(f"dice.roll failed for '{expression}': {exc}")
    expr = expression.replace(" ", "")
    m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", expr)
    if m:
        num = int(m.group(1) or 1)
        die = int(m.group(2))
        mod = int(m.group(3) or 0)
        return sum(random.randint(1, die) for _ in range(num)) + mod
    try:
        return int(expr)
    except ValueError:
        logging.error(f"Expresión de dados inválida: {expression}")
        return 0


class CombatState:
    def __init__(self):
        self.participants = []  # list of dicts
        self.order = []  # list of participant names ordered by initiative
        self.turn_index = 0
        self.hp = {}  # name -> {'hp': int, 'temp_hp': int}


class CombateCog(commands.Cog, name="Combate"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.combats = {}

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info(f"Módulo '{self.__class__.__name__}' cargado y listo.")

    def _dex_mod(self, destreza: int) -> int:
        return (destreza - 10) // 2

    async def _load_pc(self, member: discord.Member):
        user_id = str(member.id)
        pj = await self.bot.loop.run_in_executor(None, self.bot.db_utils.obtener_personaje_activo, user_id)
        if not pj:
            return None
        name = pj.get("nombre_personaje", member.display_name)
        destreza = int(pj.get("destreza") or 10)
        hp = int(pj.get("puntos_golpe_actuales") or 0)
        temp_hp = int(pj.get("puntos_golpe_temporales") or 0)
        return {
            "name": name,
            "id_personaje": pj.get("id_personaje"),
            "initiative_mod": self._dex_mod(destreza),
            "hp": hp,
            "temp_hp": temp_hp,
            "is_pc": True,
        }

    @commands.command(name="iniciar_combate", aliases=["combatir"], help="Inicia combate. Uso: !iniciar_combate [enemigos...]")
    async def iniciar_combate(self, ctx: commands.Context, *enemigos: str):
        channel_id = ctx.channel.id
        state = CombatState()
        jugadores = []
        for member in getattr(ctx.channel, "members", []):
            if member.bot:
                continue
            pc = await self._load_pc(member)
            if pc:
                jugadores.append(pc)
        enemigos_list = [
            {
                "name": enemigo,
                "initiative_mod": 0,
                "hp": 0,
                "temp_hp": 0,
                "is_pc": False,
            }
            for enemigo in enemigos
        ]
        participantes = jugadores + enemigos_list
        if not participantes:
            await ctx.send("No hay participantes para iniciar combate.")
            return
        for p in participantes:
            p["initiative"] = roll("1d20") + p.get("initiative_mod", 0)
            state.hp[p["name"]] = {"hp": p.get("hp", 0), "temp_hp": p.get("temp_hp", 0)}
        order = sorted(participantes, key=lambda x: x["initiative"], reverse=True)
        state.participants = participantes
        state.order = [p["name"] for p in order]
        self.combats[channel_id] = state
        iniciativa_msg = "\n".join(f"{p['name']}: {p['initiative']}" for p in order)
        await ctx.send(f"**Orden de iniciativa:**\n{iniciativa_msg}")

    @commands.command(name="turno", help="Muestra de quién es el turno actual")
    async def turno(self, ctx: commands.Context):
        state = self.combats.get(ctx.channel.id)
        if not state or not state.order:
            await ctx.send("No hay un combate en curso en este canal.")
            return
        actual = state.order[state.turn_index]
        await ctx.send(f"Es el turno de **{actual}**")

    @commands.command(name="siguiente", help="Pasa al siguiente combatiente")
    async def siguiente(self, ctx: commands.Context):
        state = self.combats.get(ctx.channel.id)
        if not state or not state.order:
            await ctx.send("No hay un combate en curso en este canal.")
            return
        state.turn_index = (state.turn_index + 1) % len(state.order)
        actual = state.order[state.turn_index]
        await ctx.send(f"Turno de **{actual}**")

    @commands.command(name="danyo", aliases=["daño"], help="Aplica daño. Uso: !danyo <objetivo> <expresión de dados>")
    async def danyo(self, ctx: commands.Context, objetivo: str = None, expresion: str = None):
        if not objetivo or not expresion:
            await ctx.send("Uso: !danyo <objetivo> <expresión de dados>")
            return
        state = self.combats.get(ctx.channel.id)
        if not state:
            await ctx.send("No hay un combate en curso en este canal.")
            return
        nombre = objetivo.strip()
        part = next((p for p in state.participants if p["name"].lower() == nombre.lower()), None)
        if not part:
            await ctx.send(f"No se encontró a {nombre} en el combate.")
            return
        dmg = roll(expresion)
        hp_info = state.hp.get(part["name"], {"hp": 0, "temp_hp": 0})
        temp = hp_info.get("temp_hp", 0)
        real = hp_info.get("hp", 0)
        if temp > 0:
            absorbed = min(temp, dmg)
            temp -= absorbed
            dmg -= absorbed
        hp_info["temp_hp"] = temp
        if dmg > 0:
            real = max(0, real - dmg)
        hp_info["hp"] = real
        state.hp[part["name"]] = hp_info
        if part.get("is_pc") and part.get("id_personaje"):
            await self.bot.loop.run_in_executor(None, self.bot.db_utils.actualizar_hp_personaje, part["id_personaje"], real)
        await ctx.send(f"{part['name']} tiene ahora {real} HP y {temp} temporales.")


async def setup(bot: commands.Bot):
    await bot.add_cog(CombateCog(bot))
