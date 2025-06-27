# ./modulos_bot/consulta_reglas.py
import discord
from discord.ext import commands
import logging
import asyncio  # Para asyncio.to_thread

# PROMPT DE SISTEMA específico para la consulta de reglas
SYSTEM_PROMPT_REGLAS = (
    "Eres un sabio y meticuloso erudito de las reglas de Dungeons & Dragons. "
    "Tu única función es explicar reglas o términos del juego de forma precisa y clara. "
    "Cuando se te proporcione '--- Información de Referencia de los Manuales ---', debes basar tu explicación ESTRICTA Y ÚNICAMENTE en esa información. "
    "No añadas interpretaciones personales, ejemplos no provistos en el texto,"
    " ni información de otras reglas o fuentes a menos que el texto de referencia lo indique explícitamente. "
    "Presenta la información de manera organizada. Si el contexto es directamente la definición del término preguntado, explícalo. "
    "Si el contexto proporcionado no parece ser relevante para la regla o término consultado,"
    " indica que no tienes la información específica del manual sobre ese término exacto y no intentes responder con conocimiento general."
)


class ConsultaReglas(commands.Cog, name="Consulta de Reglas"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info(f"Módulo '{self.__class__.__name__}' cargado y listo.")

    @commands.command(name='regla', aliases=['rule'], help='Consulta una regla específica de D&D. Ej: !regla Cobertura')
    async def consultar_regla_cmd(self, ctx: commands.Context, *, termino_regla: str):
        if not hasattr(self.bot, 'generate_llm_response_sync') or \
                not hasattr(self.bot, 'rag_system') or self.bot.rag_system is None:
            await ctx.send("Los sistemas de IA o RAG no están completamente listos. Por favor, avisa al administrador.")
            logging.warning("Intento de usar !regla sin RAG o LLM disponible en el bot.")
            return

        logging.info(f"Comando !regla recibido de {ctx.author.name} para: '{termino_regla}'")

        # Consulta RAG específica para reglas
        # El prefijo "Regla D&D" debe coincidir con cómo se formatean los documentos en rag_utils.py
        query_for_rag = f"Regla D&D {termino_regla.strip()}"

        rag_context_str = ""
        # Usar k=1 o k=2 para obtener los fragmentos más relevantes y específicos para la regla.
        # Demasiados fragmentos podrían confundir al LLM para esta tarea tan específica.
        relevant_docs = self.bot.rag_system.search_relevant_info(query_for_rag, k=1)

        if relevant_docs:
            rag_context_str = "\n\n--- Información de Referencia de los Manuales ---\n"
            for i, doc in enumerate(relevant_docs):
                rag_context_str += f"Referencia {i + 1}: {doc}\n"
            rag_context_str += "--- Fin de la Información de Referencia ---\n"

            # DEBUG: Enviar el contexto RAG al canal
            # debug_msg = f"**DEBUG RAG para '!regla {termino_regla[:30]}...':**\n```\n{rag_context_str[:1800].strip()}\n```"
            #await ctx.send(debug_msg)
        else:
            await ctx.send(
                f"**DEBUG: No se encontró contexto RAG específico para la regla '{termino_regla}'. Se intentará con conocimiento general si el LLM lo considera.**")

        # Construir la lista de mensajes para el LLM
        messages_for_llm = [{"role": "system", "content": SYSTEM_PROMPT_REGLAS}]

        # Para este comando, el historial de conversación general del DM es menos relevante.
        # Nos centramos en la pregunta actual y el contexto RAG específico.

        if rag_context_str:
            prompt_to_llm = (
                f"{rag_context_str}\n\n"
                f"Pregunta del jugador sobre las reglas: Explícame la regla o término '{termino_regla}' basándote en la información de referencia anterior."
            )
        else:
            # Si RAG no devuelve nada, el prompt del sistema ya indica qué hacer.
            prompt_to_llm = (
                f"Pregunta del jugador sobre las reglas: Explícame la regla o término '{termino_regla}'. "
                f"No se encontró información específica en los manuales de referencia para este término."
            )

        messages_for_llm.append({"role": "user", "content": prompt_to_llm})

        await ctx.send(f"Consultando la sabiduría ancestral sobre: '{termino_regla[:50]}...'")
        async with ctx.typing():
            try:
                # Utilizar el método síncrono del bot para la generación
                llm_response = await asyncio.to_thread(
                    self.bot.generate_llm_response_sync,
                    messages_for_llm,
                    max_new_tokens=450  # Ajustar según necesidad para explicaciones de reglas
                )
            except Exception as e:
                logging.error(f"Excepción en la generación de respuesta para !regla: {e}", exc_info=True)
                llm_response = "Tuve un problema interno al consultar los tomos antiguos."
                if "CUDA out of memory" in str(e): llm_response += " (Memoria de conjuros insuficiente en la GPU)."

        if not llm_response: llm_response = "No pude encontrar una explicación clara para esa regla en mis tomos."

        # Enviar respuesta (dividida si es larga)
        if len(llm_response) > 1990:
            for i in range(0, len(llm_response), 1990): await ctx.send(llm_response[i:i + 1990])
        else:
            await ctx.send(llm_response)

        # No actualizaremos el historial de conversación general del DM con preguntas de reglas,
        # a menos que decidas que sí deben influir en la narrativa general.


async def setup(bot: commands.Bot):
    await bot.add_cog(ConsultaReglas(bot))
    logging.info(f"Módulo '{ConsultaReglas.__name__}' cargado y listo para consultas de reglas.")
