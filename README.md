# TFG_DM_IA
# Bot de Dungeon Master con IA

Este proyecto contiene un bot de Discord que actúa como Dungeon Master (DM) para partidas de Dungeons & Dragons. Utiliza modelos de lenguaje de gran tamaño junto con un pequeño sistema de Recuperación y Generación Aumentada (RAG) basado en los archivos JSON de la carpeta `data/`.

## Características
- **Interacción con el DM** mediante el comando `!dm` definido en `modulos_bot/dm_general.py`.
- **Consulta de hechizos** con el comando `!hechizo`.
- **Explicación de reglas** a través de `!regla`.
- **Gestión de personajes** almacenados en una base de datos SQLite.
- **Resúmenes automáticos** de las respuestas del DM para mantener la coherencia de la partida.

El número de resúmenes que se guardan y se envían de vuelta al modelo depende del valor de `HISTORIA_LIMIT` definido en `dm_general.py`.

## Instalación
1. Crea un entorno virtual de Python.
2. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
3. Crea un archivo `.env` en la raíz del repositorio y define al menos tu token de Discord:
   ```env
   DISCORD_TOKEN=TU_TOKEN_AQUI
   ```
   Opcionalmente puedes configurar `MODEL_NAME` (identificador del modelo de Hugging Face) y `MAX_HISTORY_LENGTH` para personalizar la sesión.
4. Ejecuta el bot:
   ```bash
   python bot_core.py
   ```
   La primera vez se construirá automáticamente el índice RAG con los datos de `data/`.

## Uso básico
Invita al bot a tu servidor de Discord y utiliza los comandos:
- `!help` – Muestra todos los comandos disponibles del bot.
- `!dm <texto>` – Narración interactiva del Dungeon Master.
- `!hechizo <nombre>` – Obtiene información oficial de un hechizo.
- `!regla <término>` – Consulta reglas de D&D.

Todo el código de comandos y utilidades de base de datos se encuentra en la carpeta `modulos_bot/`, y las funciones de RAG están en `rag_utils.py`.

Este proyecto contiene utilidades para un sistema de RAG y un bot de Discord relacionado con Dungeons & Dragons.

## Desactivar FIREBALL

La función `rag_utils.load_all_data` puede cargar de forma opcional ejemplos del dataset [FIREBALL](https://huggingface.co/datasets/lara-martin/FIREBALL). Por defecto se intentará descargar este conjunto de datos. Si se desea omitirlo (por ejemplo en entornos sin conexión), define la variable de entorno `LOAD_FIREBALL=0` antes de ejecutar el programa o pasa `load_fireball=False` al llamar a `load_all_data`.

```bash
export LOAD_FIREBALL=0
python bot_core.py
```

Con esta variable establecida en `0` (o en valores como `false`/`no`) se saltará la descarga y se cargará únicamente la información local.

