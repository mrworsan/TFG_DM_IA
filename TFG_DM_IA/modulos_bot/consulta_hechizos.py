# ./modulos_bot/consulta_hechizos.py
import discord
from discord.ext import commands
import logging
import asyncio

# PROMPT DE SISTEMA específico para la consulta de hechizos
SYSTEM_PROMPT_HECHIZOS = (
    "Eres un Archimago experto en el conocimiento de conjuros de Dungeons & Dragons. "
    "Tu única función es describir hechizos de forma precisa, clara y completa, basándote ESTRICTA Y ÚNICAMENTE "
    "en la 'Información de Referencia de los Manuales (Hechizos)' que se te proporciona. "
    "Presenta los detalles del hechizo de manera organizada, incluyendo siempre que sea posible: Nombre del Hechizo,"
    " Nivel y Escuela, Tiempo de Lanzamiento, Alcance, Componentes (V, S, M y el material específico si se detalla), Duración y la Descripción completa de su efecto. "
    "**Si el hechizo inflige daño, asegúrate de especificar claramente la cantidad de daño (por ejemplo, '2d6 de daño de fuego'"
    ", '1d10 de daño perforante') y el tipo de daño. Indica también si se requiere una tirada de salvación para evitar o reducir este daño,"
    " y qué tipo de salvación es (ej. 'Tirada de Salvación de Destreza para mitad de daño').** "
    "Si la información de referencia incluye detalles sobre cómo el hechizo funciona 'A Mayor Nivel' o 'Mejora de Truco', incorpóralos textualmente. "
    "No inventes información, no añadas interpretaciones personales, ni ejemplos no provistos en el texto, ni información de otras fuentes no incluidas en la referencia. "
    "Si la información de referencia proporcionada no parece ser relevante para el hechizo consultado o está vacía,"
    " indica claramente que no tienes la información específica del manual sobre ese hechizo exacto y no intentes responder con conocimiento general."
)

class ConsultaHechizos(commands.Cog, name="Consulta de Hechizos"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info(f"Módulo '{self.__class__.__name__}' cargado y listo.")

    @commands.command(name='hechizo', aliases=['spell'], help='Consulta información sobre un hechizo de D&D. Ej: !hechizo Bola de Fuego')
    async def consultar_hechizo_cmd(self, ctx: commands.Context, *, nombre_hechizo: str):
        if not hasattr(self.bot, 'generate_llm_response_sync') or \
           not hasattr(self.bot, 'rag_system') or self.bot.rag_system is None:
            await ctx.send("Los sistemas de IA o RAG no están completamente listos. Por favor, avisa al administrador.")
            logging.warning("Intento de usar !hechizo sin RAG o LLM disponible en el bot.")
            return

        nombre_hechizo_limpio = nombre_hechizo.strip()
        logging.info(f"Comando !hechizo recibido de {ctx.author.name} para: '{nombre_hechizo_limpio}'")

        query_for_rag = f"Hechizo {nombre_hechizo_limpio}"
        rag_context_str = ""
        relevant_docs = self.bot.rag_system.search_relevant_info(query_for_rag, k=1)

        if relevant_docs:
            rag_context_str = "\n\n--- Información de Referencia de los Manuales (Hechizos) ---\n"
            for i, doc in enumerate(relevant_docs):
                rag_context_str += f"Referencia {i + 1}:\n{doc}\n"
            rag_context_str += "--- Fin de la Información de Referencia ---\n"
        else:
            logging.info(f"No se encontró contexto RAG específico para el hechizo '{nombre_hechizo_limpio}'.")

        messages_for_llm = [{"role": "system", "content": SYSTEM_PROMPT_HECHIZOS}]

        if rag_context_str:
            prompt_to_llm = (
                f"{rag_context_str}\n\n"
                f"Pregunta del jugador sobre hechizos: Describe el hechizo '{nombre_hechizo_limpio}' basándote ESTRICTAMENTE en la información de referencia proporcionada. "
                f"Asegúrate de incluir todos los detalles relevantes como Nivel, Escuela, Tiempo de Lanzamiento, Alcance, Componentes, Duración, la descripción completa del efecto, "
                f"y específicamente cualquier información de daño (cantidad, tipo de dado, tipo de daño) y tiradas de salvación asociadas."
            )
        else:
            prompt_to_llm = (
                f"Pregunta del jugador sobre hechizos: Describe el hechizo '{nombre_hechizo_limpio}'. "
                f"No se ha encontrado información de referencia para este hechizo."
            )

        messages_for_llm.append({"role": "user", "content": prompt_to_llm})

        await ctx.send(f"Consultando los arcanos saberes sobre: '{nombre_hechizo_limpio[:50]}...'")
        async with ctx.typing():
            try:
                llm_response = await asyncio.to_thread(
                    self.bot.generate_llm_response_sync,
                    messages_for_llm,
                    max_new_tokens=700,
                    temperature=0.5
                )
            except Exception as e:
                logging.error(f"Excepción en la generación de respuesta para !hechizo: {e}", exc_info=True)
                llm_response = "Los hilos de la magia se enredaron; no pude obtener la descripción completa de ese hechizo."
                if "CUDA out of memory" in str(e):
                    llm_response += " (La energía para el conjuro excede mis reservas actuales - GPU)."
                elif "probability tensor contains nan" in str(e):
                    llm_response += " (Una perturbación en el Tejido Mágico impidió la consulta)."

        if not llm_response:
            llm_response = "Mis grimorios no contienen información sobre ese hechizo, o la magia recuperada fue insuficiente."

        if len(llm_response) > 1990:
            partes = [llm_response[i:i + 1990] for i in range(0, len(llm_response), 1990)]
            for parte in partes:
                await ctx.send(parte)
        else:
            await ctx.send(llm_response)

async def setup(bot: commands.Bot):
    await bot.add_cog(ConsultaHechizos(bot))
    logging.info(f"Módulo '{ConsultaHechizos.__name__}' cargado y listo para consultas de hechizos.")
