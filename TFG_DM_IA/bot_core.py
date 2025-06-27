# TFG_DM_IA/bot_core.py
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import logging
import asyncio

# LLM imports
from transformers import AutoModelForCausalLM, AutoTokenizer

import torch

# RAG utils e importación condicional
try:
    import rag_utils
except ImportError:
    logging.error("CRITICAL: No se pudo importar rag_utils.py. La funcionalidad RAG estará deshabilitada.")
    rag_utils = None

# DB utils e importación condicional
try:
    from modulos_bot import db_utils
except ImportError:
    logging.error("CRITICAL: No se pudo importar db_utils.py. La funcionalidad de BD estará deshabilitada.")
    db_utils = None

# --- Configuración Inicial ---
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s')

if DISCORD_TOKEN is None:
    logging.critical("CRITICAL: DISCORD_TOKEN no encontrado en el archivo .env. El bot no puede iniciarse.")
    exit()

# --- Definición de BASE_DIR para rutas ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(BASE_DIR, 'modulos_bot')


class DungeonMasterBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.MODEL_NAME = os.getenv('MODEL_NAME', 'mistralai/Mistral-7B-Instruct-v0.3')
        self.conversation_history = {}  # Clave: channel_id, Valor: lista de mensajes
        self.MAX_HISTORY_LENGTH = int(os.getenv('MAX_HISTORY_LENGTH', 10))  # Aumentado un poco

        self.llm_model = None
        self.tokenizer = None
        self.rag_system = None
        self.db_utils = db_utils  # Asigna el módulo importado
        # Exponer un alias común para la generación de respuestas con el LLM
        self.generate_llm_response = self.generate_llm_response_sync

    def load_llm_model_sync(self):
        """Carga el modelo LLM y el tokenizador. Esta es una operación síncrona."""
        if self.llm_model is None:
            logging.info(f"Cargando modelo LLM: {self.MODEL_NAME} en {self.device}...")
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(self.MODEL_NAME)
                if self.tokenizer.pad_token is None:
                    self.tokenizer.pad_token = self.tokenizer.eos_token

                compute_dtype = torch.bfloat16 if self.device == "cuda" and \
                                                  torch.cuda.is_available() and \
                                                  torch.cuda.get_device_capability()[0] >= 8 else torch.float16


                self.llm_model = AutoModelForCausalLM.from_pretrained(
                    self.MODEL_NAME,
                    torch_dtype=compute_dtype,
                    device_map="auto",

                )
                self.llm_model.eval()  # Poner el modelo en modo de evaluación
                logging.info(f"Modelo {self.MODEL_NAME} cargado exitosamente en dispositivo: {self.llm_model.device}.")
            except Exception as e:
                logging.error(f"Error crítico al cargar LLM: {e}", exc_info=True)
                # No establecer a None aquí permite reintentos si es necesario, o manejarlo en el llamador

    def generate_llm_response_sync(self, message_list, max_new_tokens=350, temperature=0.6, top_p=0.9):  # Renombrado
        """Genera respuesta del LLM. Operación síncrona."""
        if not self.llm_model or not self.tokenizer:
            logging.warning("LLM o tokenizer no disponibles en `generate_llm_response_sync`.")
            return "Motor de IA no está listo en este momento."

        log_messages = message_list[-2:] if len(message_list) >= 2 else message_list
        logging.info(
            f"Generando respuesta LLM (max_tokens: {max_new_tokens}, temp: {temperature}) para: {log_messages}")

        try:
            # Asegurarse de que los inputs están en el mismo dispositivo que el modelo
            inputs = self.tokenizer.apply_chat_template(
                message_list,
                add_generation_prompt=True,
                return_tensors="pt"
            ).to(self.llm_model.device)  # Mover inputs al dispositivo del modelo

            with torch.no_grad():  # Desactivar cálculo de gradientes para inferencia
                outputs = self.llm_model.generate(
                    inputs,
                    max_new_tokens=max_new_tokens,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                    do_sample=True,
                    temperature=temperature,
                    top_p=top_p
                )
            response_text = self.tokenizer.decode(outputs[0][inputs.shape[1]:], skip_special_tokens=True)
            logging.info(f"Respuesta LLM generada (longitud: {len(response_text)}): {response_text[:100]}...")
            return response_text.strip()
        except Exception as e:
            logging.error(f"Error en generación de texto LLM: {e}", exc_info=True)
            if "CUDA out of memory" in str(e): return "Error: Memoria GPU insuficiente. Intenta una petición más corta."
            return "Error al generar respuesta del LLM."

    async def setup_hook(self):
        """Hook que se ejecuta después del login pero antes de conectarse a la gateway."""
        logging.info("Ejecutando setup_hook...")

        # Cargar LLM (es síncrono, así que lo ejecutamos en un executor para no bloquear)
        logging.info("Iniciando carga de modelo LLM...")
        await self.loop.run_in_executor(None, self.load_llm_model_sync)
        if self.llm_model and self.tokenizer:
            logging.info("Modelo LLM y tokenizador cargados.")
        else:
            logging.error("Fallo al cargar el modelo LLM o el tokenizador. El bot podría no funcionar correctamente.")
            # Podrías decidir salir o continuar con funcionalidad limitada

        # Inicializar RAG
        if rag_utils:
            logging.info("Inicializando sistema RAG (esto puede tardar si el índice no existe)...")
            load_fb = os.getenv("LOAD_FIREBALL", "1").lower() not in ("0", "false", "no")
            all_docs_for_rag = await self.loop.run_in_executor(
                None,
                rag_utils.load_all_data,
                rag_utils.DATA_FOLDER_PATH,
                load_fb,
            )
            if all_docs_for_rag:
                self.rag_system = rag_utils  # Adjuntar el módulo rag_utils
                # Construir/cargar el índice en un thread para no bloquear
                await self.loop.run_in_executor(None, self.rag_system.build_or_load_index, all_docs_for_rag)
                logging.info("Sistema RAG inicializado y disponible.")
            else:
                logging.warning("No se cargaron documentos para el índice RAG. La funcionalidad RAG estará limitada.")
        else:
            logging.error("Módulo rag_utils no importado. Funcionalidad RAG deshabilitada.")

        # Inicializar Base de Datos
        if self.db_utils:
            logging.info("Inicializando base de datos...")
            await self.loop.run_in_executor(None, self.db_utils.inicializar_bd)  #
            logging.info("Base de datos inicializada.")
        else:
            logging.warning("Módulo db_utils no disponible. Funcionalidad de BD deshabilitada.")

        # Cargar Cogs
        logging.info(f"Buscando módulos en: {MODULES_DIR}")
        loaded_modules_count = 0
        # Ajustar los nombres de los cogs si los has cambiado
        cogs_a_cargar = ['consulta_hechizos', 'Consulta_reglas', 'gestion_personajes', 'dm_general', 'dice']
        # Asumimos que tendrás un 'dm_general.py' para el comando !dm

        for cog_filename in os.listdir(MODULES_DIR):
            if cog_filename.endswith('.py') and cog_filename != '__init__.py' and cog_filename != 'db_utils.py':
                cog_name = cog_filename[:-3]
                extension_name = f'modulos_bot.{cog_name}'
                if cog_name in cogs_a_cargar or True:  # Cargar todos los .py excepto db_utils e __init__
                    try:
                        await self.load_extension(extension_name)
                        logging.info(f'Módulo cargado exitosamente: {extension_name}')
                        loaded_modules_count += 1
                    except commands.ExtensionAlreadyLoaded:
                        logging.warning(f'Módulo {extension_name} ya estaba cargado.')
                    except commands.ExtensionNotFound:
                        logging.error(f'Módulo {extension_name} no encontrado.')
                    except commands.NoEntryPointError:
                        logging.error(f'Módulo {extension_name} no tiene una función setup().')
                    except Exception as e:
                        logging.error(f'Fallo al cargar módulo {extension_name}: {e}', exc_info=True)

        if loaded_modules_count == 0:
            logging.warning("No se cargaron módulos (cogs) de la carpeta 'modulos_bot'.")
        else:
            logging.info(f"--- {loaded_modules_count} módulos (cogs) cargados. ---")

    async def on_ready(self):
        logging.info(f"--- {self.user.name} conectado a Discord! (ID: {self.user.id}) ---")
        logging.info(f"Dispositivo para PyTorch: {self.device}")
        if self.llm_model:
            logging.info(f"Modelo LLM '{self.MODEL_NAME}' está cargado y listo.")
        else:
            logging.warning(f"Modelo LLM '{self.MODEL_NAME}' NO está cargado.")
        if self.rag_system:
            # Verificar si el índice RAG se cargó/construyó correctamente
            if hasattr(self.rag_system, 'faiss_index') and self.rag_system.faiss_index and \
                    hasattr(self.rag_system, 'indexed_docs') and self.rag_system.indexed_docs:
                logging.info(f"Sistema RAG listo con {self.rag_system.faiss_index.ntotal} documentos en el índice.")
            else:
                # Intentar cargarlo/construirlo de nuevo si falla, asumiendo que all_docs_for_rag ya se cargó
                # Esto es una contingencia, idealmente build_or_load_index en setup_hook debería haberlo manejado
                logging.warning(
                    "Índice RAG no parece estar completamente listo, intentando cargar/construir de nuevo...")
                try:
                    all_docs_for_rag = await self.loop.run_in_executor(None, rag_utils.load_all_data,
                                                                       rag_utils.DATA_FOLDER_PATH)
                    if all_docs_for_rag:
                        await self.loop.run_in_executor(None, self.rag_system.build_or_load_index, all_docs_for_rag)
                        if hasattr(self.rag_system, 'faiss_index') and self.rag_system.faiss_index:
                            logging.info(
                                f"Sistema RAG ahora listo con {self.rag_system.faiss_index.ntotal} documentos.")
                        else:
                            logging.error("Fallo al inicializar el índice RAG en el reintento.")
                    else:
                        logging.error("No se pudieron cargar documentos RAG en el reintento.")
                except Exception as e:
                    logging.error(f"Error al re-inicializar RAG en on_ready: {e}", exc_info=True)


        else:
            logging.warning("Sistema RAG no disponible.")
        await asyncio.sleep(0)
        if self.db_utils:
            logging.info("Sistema de Base de Datos (db_utils) disponible.")
        else:
            logging.warning("Sistema de Base de Datos (db_utils) NO disponible.")
        logging.info("--- Bot completamente listo y operativo. ---")

    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return
        # Aquí solo procesamos comandos. La lógica de conversación general con el LLM
        await self.process_commands(message)


# --- Intents del Bot ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# --- Creación y Ejecución de la Instancia del Bot ---
bot_instance = DungeonMasterBot(command_prefix='!', intents=intents, help_command=None)


async def main():
    async with bot_instance:  # Usar el gestor de contexto para el bot
        await bot_instance.start(DISCORD_TOKEN)


if __name__ == "__main__":
    if DISCORD_TOKEN:
        asyncio.run(main())
    else:
        logging.critical("DISCORD_TOKEN no está definido en .env. Saliendo.")
