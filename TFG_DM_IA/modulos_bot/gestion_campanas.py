import discord
from discord.ext import commands
import asyncio
import logging

SYSTEM_PROMPT_CAMPAIGN = (
    "Eres un creador de campañas experto en Dungeons & Dragons. "
    "Con la información proporcionada por el usuario deberás generar una sinopsis concisa y atractiva "
    "para la aventura que sirva de introducción. Utiliza únicamente la información ofrecida."
)

class GestionCampanas(commands.Cog, name="Gestión de Campañas"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.campaigns = {}

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info(f"Módulo '{self.__class__.__name__}' cargado y listo.")

    @commands.command(name='crear_campana', aliases=['nueva_campana'], help='Crea una nueva campaña de rol de forma interactiva.')
    async def crear_campana_cmd(self, ctx: commands.Context):
        def check(m: discord.Message):
            return m.author == ctx.author and m.channel == ctx.channel

        preguntas = [
            ("Indica el tipo de partida (mazmorreo, exploración, política, etc.):", str),
            ("¿Cuántas sesiones estimas que durará la campaña?", int),
            ("¿Qué dificultad deseas? (fácil, media, difícil...)", str)
        ]
        respuestas = []
        for texto, conv in preguntas:
            await ctx.send(texto)
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=120)
            except asyncio.TimeoutError:
                await ctx.send('Tiempo agotado. Creación cancelada.')
                return
            if msg.content.lower() == 'cancelar':
                await ctx.send('Creación cancelada.')
                return
            try:
                respuestas.append(conv(msg.content.strip()))
            except Exception:
                await ctx.send('Entrada no válida. Creación cancelada.')
                return

        tipo, duracion, dificultad = respuestas
        channel_id = str(ctx.channel.id)

        # Generar sinopsis con el LLM si está disponible
        synopsis = f"Campaña de tipo {tipo}, {duracion} sesiones, dificultad {dificultad}."
        if hasattr(self.bot, 'generate_llm_response_sync') and self.bot.llm_model:
            prompt = (
                f"Tipo de partida: {tipo}\n"
                f"Duración estimada: {duracion} sesiones\n"
                f"Dificultad: {dificultad}\n"
                "Redacta una breve sinopsis para presentar esta campaña a los jugadores."
            )
            messages = [{"role": "system", "content": SYSTEM_PROMPT_CAMPAIGN},
                        {"role": "user", "content": prompt}]
            try:
                synopsis = await asyncio.to_thread(
                    self.bot.generate_llm_response_sync,
                    messages,
                    300,
                    0.7
                )
            except Exception as e:
                logging.error(f"Error al generar sinopsis de campaña: {e}", exc_info=True)

        # Verificar que la sinopsis termine correctamente. Si no, solicitar una continuación corta
        if synopsis and not synopsis.strip().endswith((".", "!", "?")):
            if hasattr(self.bot, 'generate_llm_response_sync') and self.bot.llm_model:
                continuation_messages = messages + [
                    {"role": "assistant", "content": synopsis},
                    {"role": "user", "content": "Continúa y finaliza la sinopsis."}
                ]
                try:
                    continuation = await asyncio.to_thread(
                        self.bot.generate_llm_response_sync,
                        continuation_messages,
                        60,
                        0.7
                    )
                    synopsis = synopsis.rstrip() + " " + continuation.strip()
                except Exception as e:
                    logging.error(f"Error al completar sinopsis de campaña: {e}", exc_info=True)

        self.campaigns[channel_id] = {
            "tipo": tipo,
            "duracion": duracion,
            "dificultad": dificultad,
            "sinopsis": synopsis,
        }

        await ctx.send("Campaña creada. Usa `!iniciar_campana` para comenzar la aventura.")

    @commands.command(name='iniciar_campana', aliases=['comenzar_campana'], help='Inicia la aventura con la sinopsis de la campaña creada.')
    async def iniciar_campana_cmd(self, ctx: commands.Context):
        channel_id = str(ctx.channel.id)
        camp = self.campaigns.get(channel_id)
        if not camp:
            await ctx.send('No hay ninguna campaña creada para este canal.')
            return

        intro = camp['sinopsis']
        if hasattr(self.bot, 'conversation_history'):
            history = self.bot.conversation_history.setdefault(channel_id, [])
            # Registrar en el historial que la campaña comenzó para mantener el orden user/assistant
            history.append({"role": "user", "content": "Comenzar campaña"})
            history.append({"role": "assistant", "content": intro})
        await ctx.send(intro)

async def setup(bot: commands.Bot):
    await bot.add_cog(GestionCampanas(bot))
    logging.info("Módulo 'GestionCampanas' cargado y listo para gestionar campañas.")
