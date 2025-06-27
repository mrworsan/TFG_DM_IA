import discord
from discord.ext import commands
import logging
import asyncio  # Para asyncio.to_thread si es necesario para el LLM
from .utils_summaries import resumir_respuesta

# PROMPT DE SISTEMA para el DM General
SYSTEM_PROMPT_DM = (
    "Eres un Dungeon Master de Dungeons & Dragons experimentado, creativo y ecuánime. "
    "Tu objetivo es narrar una aventura de fantasía interactiva y emocionante. "
    "Cuando los jugadores te hablen, responde como un DM, describiendo el entorno, "
    "los resultados de sus acciones, interpretando a los Personajes No Jugadores (PNJ), "
    "y presentando desafíos. Utiliza la 'Información de Referencia de los Manuales' "
    "que se te proporcione para enriquecer tus descripciones y asegurar la coherencia con el mundo del juego. "
    "Mantén un tono apropiado para una partida de D&D. Sé descriptivo e inmersivo. "
    "Si se te proporciona un historial de conversación, úsalo para mantener la continuidad. "
    "Si se te proporciona información sobre el personaje del jugador, tenla en cuenta al narrar. "
    "Si la información de referencia no es directamente relevante a la pregunta/acción actual del jugador, "
    "confía en tu conocimiento general de D&D y fantasía para continuar la narración de forma creativa y coherente, "
    "pero no contradigas la información de los manuales si esta es aplicable. "
    "Evita mencionar inventarios o la 'Hoja de Personaje' salvo que el jugador lo solicite expresamente. "
    "Si sospechas que hay pistas o trampas ocultas, pide al jugador las tiradas pertinentes (p.ej. Percepción o Investigación). "
    "Introduce nuevos retos o enemigos cuando sea apropiado y evita repetir palabra por palabra descripciones ya dadas. "
    "Cada turno debe reflejar un avance o cambio en la situación. "
    "Finaliza cada respuesta con una pregunta corta que invite al jugador a decidir su siguiente acción y espera la respuesta."
)


class DMGeneral(commands.Cog, name="DM General"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # self.rag_system y self.db_utils se acceden a través de self.bot
        self.HISTORIA_LIMIT = 5  # Número de eventos históricos a proporcionar al LLM
        self.historia_resumenes = {}

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info(f"Módulo '{self.__class__.__name__}' cargado y listo.")

    @commands.command(name='dm', aliases=['dungeonmaster', 'narrar'],
                      help='Interactúa con el Dungeon Master IA. Ej: !dm Exploras la cueva oscura.')
    async def dm_interact(self, ctx: commands.Context, *, user_input: str = None):
        if not user_input:
            await ctx.send(
                f"Hola {ctx.author.mention}, ¿en qué puedo ayudarte como tu Dungeon Master? Describe tu acción o pregunta.")
            return

        channel_id = str(ctx.channel.id)
        user_id_str = str(ctx.author.id)

        # 1. Inicializar/Recuperar historial de conversación del canal
        if channel_id not in self.bot.conversation_history:
            self.bot.conversation_history[channel_id] = []

        # Obtener últimos eventos de la historia del canal para mantener el hilo
        if channel_id not in self.historia_resumenes:
            self.historia_resumenes[channel_id] = []
            if hasattr(self.bot, "db_utils") and self.bot.db_utils is not None:
                try:
                    eventos = await self.bot.loop.run_in_executor(
                        None,
                        self.bot.db_utils.obtener_historia_reciente,
                        channel_id,
                        self.HISTORIA_LIMIT,
                    )
                    self.historia_resumenes[channel_id] = [
                        ev.get("resumen_evento", "") for ev in reversed(eventos) if ev.get("resumen_evento")
                    ]
                except Exception as e:
                    logging.error(f"Error al recuperar historia reciente: {e}", exc_info=True)

        historia_context_str = ""
        resumenes = self.historia_resumenes.get(channel_id, [])
        if resumenes:
            historia_context_str = "\n\n-- Historia Reciente --\n"
            for resumen in reversed(resumenes[-self.HISTORIA_LIMIT:]):
                historia_context_str += f"* {resumen}\n"
            historia_context_str += "-- Fin de la Historia Reciente --\n"

        # 2. Obtener información del personaje activo (si existe)
        personaje_info_str = "El jugador no tiene un personaje activo."
        personaje_activo = None
        try:
            personaje_activo = await self.bot.loop.run_in_executor(None, self.bot.db_utils.obtener_personaje_activo,
                                                                   user_id_str)
            if personaje_activo:
                campos_personaje = {
                    "nombre_personaje": "Nombre", "raza": "Raza", "clase": "Clase",
                    "nivel": "Nivel", "puntos_golpe_actuales": "PG Actuales",
                    "puntos_golpe_maximos": "PG Máximos", "clase_armadura": "CA"
                }
                info_parts = [f"{display_name}: {personaje_activo.get(key, 'N/A')}"
                              for key, display_name in campos_personaje.items() if
                              personaje_activo.get(key) is not None]
                if info_parts:
                    personaje_info_str = (
                        f"[INFORMACIÓN PARA EL DM - NO MENCIONAR DIRECTAMENTE] Datos de {ctx.author.display_name}: "
                        + ", ".join(info_parts)
                        + "."
                    )
        except Exception as e:
            logging.error(f"Error al obtener personaje activo para el prompt del DM: {e}", exc_info=True)
            personaje_info_str = "Error al obtener información del personaje."

        # 3. Consulta RAG (opcional, pero recomendado para dar contexto al LLM)
        #    La query para RAG puede ser el input del usuario o algo más elaborado.
        rag_context_str = ""
        if self.bot.rag_system:
            try:
                # Query RAG con el input del usuario para obtener contexto relevante de los manuales
                relevant_docs = await asyncio.to_thread(
                    self.bot.rag_system.search_relevant_info,
                    user_input,
                    k=2,
                )  # k=2 o 3
                if relevant_docs:
                    rag_context_str = "\n\n--- Información de Referencia de los Manuales (Potencialmente Relevante) ---\n"
                    for i, doc in enumerate(relevant_docs):
                        rag_context_str += f"Referencia {i + 1}: {doc}\n"
                    rag_context_str += "--- Fin de la Información de Referencia ---\n"
            except Exception as e:
                logging.error(f"Error durante la búsqueda RAG en !dm: {e}", exc_info=True)

        # 4. Construir el prompt para el LLM
        system_prompt = SYSTEM_PROMPT_DM
        if personaje_info_str:
            system_prompt = f"{SYSTEM_PROMPT_DM}\n{personaje_info_str}"

            messages_for_llm = [{"role": "system", "content": system_prompt}]

        # Añadir historial de conversación (si existe y no está vacío)
        if self.bot.conversation_history[channel_id]:
            for msg_hist in self.bot.conversation_history[channel_id]:
                messages_for_llm.append(msg_hist)

        # Añadir el input actual del usuario y el contexto RAG
        prompt_to_llm = f"Acción/pregunta del jugador ({ctx.author.display_name}): {user_input}\n\n"
        if historia_context_str:
            prompt_to_llm += historia_context_str
        if rag_context_str:
            prompt_to_llm += rag_context_str

        messages_for_llm.append({"role": "user", "content": prompt_to_llm})

        # 5. Generar respuesta del LLM
        await ctx.send(f"Procesando tu acción: '{user_input[:100]}...'")
        async with ctx.typing():
            try:
                # Usar el metodo síncrono generate_llm_response_sync en un executor
                llm_response = await asyncio.to_thread(
                    self.bot.generate_llm_response_sync,
                    messages_for_llm,
                    max_new_tokens=400,
                    temperature=0.5,
                )
            except Exception as e:
                logging.error(f"Excepción en la generación de respuesta para !dm: {e}", exc_info=True)
                llm_response = "El Vacío Interplanar interfiere con mis sentidos... no pude procesar eso."

        if not llm_response:
            llm_response = "El DM reflexiona en silencio..."

        # 6. Enviar respuesta y actualizar historial
        if len(llm_response) > 1990:
            # Manejo de mensajes largos
            for i in range(0, len(llm_response), 1990):
                await ctx.send(llm_response[i:i + 1990])
        else:
            await ctx.send(llm_response)

        # Actualizar historial de conversación del canal
        self.bot.conversation_history[channel_id].append(
            {"role": "user", "content": f"({ctx.author.display_name}) {user_input}"})
        self.bot.conversation_history[channel_id].append({"role": "assistant", "content": llm_response})

        # Generar y registrar un resumen breve del evento
        resumen_evento = None
        try:
            resumen_evento = await asyncio.to_thread(resumir_respuesta, self.bot, llm_response)
        except Exception as e:
            logging.error(f"Error al resumir respuesta del DM: {e}", exc_info=True)
            resumen_evento = llm_response[:150]

        if resumen_evento:
            self.historia_resumenes.setdefault(channel_id, []).append(resumen_evento)
            if len(self.historia_resumenes[channel_id]) > self.HISTORIA_LIMIT:
                self.historia_resumenes[channel_id] = self.historia_resumenes[channel_id][-self.HISTORIA_LIMIT:]

            if hasattr(self.bot, "db_utils") and self.bot.db_utils is not None:
                try:
                    pj_nombre = personaje_activo.get("nombre_personaje") if 'personaje_activo' in locals() and personaje_activo else None
                    await self.bot.loop.run_in_executor(
                        None,
                        self.bot.db_utils.anadir_evento_historia,
                        channel_id,
                        resumen_evento,
                        self.bot.user.id if self.bot.user else None,
                        pj_nombre,
                        None,
                    )
                except Exception as e:
                    logging.error(f"Error al guardar evento en la historia: {e}", exc_info=True)

        # Mantener el historial con una longitud máxima
        if len(self.bot.conversation_history[
                   channel_id]) > self.bot.MAX_HISTORY_LENGTH * 2:  # *2 porque son pares de user/assistant
            # Eliminar los mensajes más antiguos (los primeros N pares)
            num_to_remove = (len(self.bot.conversation_history[channel_id]) - self.bot.MAX_HISTORY_LENGTH * 2)
            self.bot.conversation_history[channel_id] = self.bot.conversation_history[channel_id][num_to_remove:]
            logging.info(f"Historial del canal {channel_id} truncado a {self.bot.MAX_HISTORY_LENGTH} intercambios.")

    @commands.command(name='limpiar_historial_dm', aliases=['cleardm', 'resetdm'],
                      help='Limpia el historial de conversación del DM para este canal.')
    async def limpiar_historial_dm(self, ctx: commands.Context):
        channel_id = str(ctx.channel.id)
        if channel_id in self.bot.conversation_history:
            self.bot.conversation_history[channel_id] = []
            if channel_id in self.historia_resumenes:
                self.historia_resumenes[channel_id] = []
            await ctx.send("El historial de conversación del DM para este canal ha sido limpiado.")
            logging.info(f"Historial del DM limpiado para el canal {channel_id} por {ctx.author.name}")
        else:
            await ctx.send("No hay historial de DM que limpiar para este canal.")

    @commands.command(name='historia', aliases=['historia_reciente'],
                      help='Muestra un resumen de los últimos eventos de la partida.')
    async def historia_reciente_cmd(self, ctx: commands.Context, limite: int = 5):
        channel_id = str(ctx.channel.id)
        if limite > 10:
            limite = 10
        if hasattr(self.bot, "db_utils") and self.bot.db_utils is not None:
            try:
                eventos = await self.bot.loop.run_in_executor(None, self.bot.db_utils.obtener_historia_reciente,
                                                               channel_id, limite)
                if not eventos:
                    await ctx.send("No hay historia registrada para este canal.")
                    return
                embed = discord.Embed(title="Historia Reciente", color=discord.Color.purple())
                for ev in reversed(eventos):
                    ts = ev.get('timestamp', '')
                    resumen = ev.get('resumen_evento', '')
                    embed.add_field(name=str(ts)[:19], value=resumen or 'Sin resumen', inline=False)
                await ctx.send(embed=embed)
            except Exception as e:
                logging.error(f"Error al obtener historia reciente para mostrar: {e}", exc_info=True)
                await ctx.send("No se pudo recuperar la historia reciente.")
        else:
            await ctx.send("La base de datos no está disponible para consultar la historia.")


async def setup(bot: commands.Bot):
    # Asegurar que las dependencias (rag_system, db_utils) estén en el bot
    if not hasattr(bot, 'rag_system') or bot.rag_system is None:
        logging.warning("DMGeneral Cog: rag_system no encontrado en el bot. La funcionalidad RAG estará limitada.")
    if not hasattr(bot, 'db_utils') or bot.db_utils is None:
        logging.warning("DMGeneral Cog: db_utils no encontrado en el bot. La info de personaje no se usará.")

    await bot.add_cog(DMGeneral(bot))
    logging.info("Cog 'DMGeneral' añadido al bot.")
