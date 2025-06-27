# ./modulos_bot/db_utils.py
import sqlite3
import logging
import os
from datetime import datetime # Necesario para el timestamp

# Determinar la ruta de la base de datos
# Asumiendo que db_utils.py está en modulos_bot, y la BD estará en TFG_DM_IA/data/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, "data/BDD")
DB_PATH = os.path.join(DB_DIR, "personajes_dnd.db")

def obtener_conexion_db():
    """Establece y devuelve una conexión a la base de datos."""
    os.makedirs(DB_DIR, exist_ok=True) # Asegura que la carpeta data exista
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;") # Habilitar claves foráneas
    return conn

def inicializar_bd():
    """Crea las tablas necesarias si no existen."""
    conn = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()

        # Tabla de Personajes
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Personajes (
            id_personaje INTEGER PRIMARY KEY AUTOINCREMENT,
            id_usuario_discord TEXT NOT NULL,nombre_personaje TEXT NOT NULL,raza TEXT,clase TEXT,
            subclase TEXT,nivel INTEGER DEFAULT 1,trasfondo TEXT,
            alineamiento TEXT,puntos_golpe_maximos INTEGER DEFAULT 10,
            puntos_golpe_actuales INTEGER DEFAULT 10,puntos_golpe_temporales INTEGER DEFAULT 0,
            clase_armadura INTEGER DEFAULT 10,velocidad TEXT DEFAULT '30 pies',
            fuerza INTEGER DEFAULT 10,destreza INTEGER DEFAULT 10,
            constitucion INTEGER DEFAULT 10,inteligencia INTEGER DEFAULT 10,
            sabiduria INTEGER DEFAULT 10,carisma INTEGER DEFAULT 10,
            bono_competencia INTEGER DEFAULT 2,inspiracion INTEGER DEFAULT 0,
            equipo_principal TEXT,notas_personaje TEXT,
            personaje_activo INTEGER DEFAULT 0,UNIQUE(id_usuario_discord, nombre_personaje)
        )
        """)
        logging.info("Tabla 'Personajes' verificada/creada.")

        # Tabla de Registro de Historia
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS RegistroHistoria (
            id_entrada INTEGER PRIMARY KEY AUTOINCREMENT,
            id_canal_discord TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            resumen_evento TEXT NOT NULL,
            id_usuario_narrador TEXT,
            personajes_implicados TEXT,
            etiquetas TEXT 
        )
        """)
        logging.info("Tabla 'RegistroHistoria' verificada/creada.")

        conn.commit()
        logging.info("Base de datos inicializada y tablas aseguradas.")
    except sqlite3.Error as e:
        logging.error(f"Error al inicializar la base de datos: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

# --- Funciones CRUD para Personajes ---
def registrar_personaje(id_usuario_discord: str, nombre_personaje: str, raza: str = None, clase: str = None, nivel: int = 1, max_hp: int = 10, ca: int = 10, trasfondo: str = None, alineamiento: str = None):
    """Registra un nuevo personaje para un usuario."""
    conn = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()

        # Verificar si el usuario ya tiene un personaje activo
        cursor.execute("SELECT 1 FROM Personajes WHERE id_usuario_discord = ? AND personaje_activo = 1", (id_usuario_discord,))
        personaje_activo_existente = cursor.fetchone()

        hacer_este_activo = 0
        if not personaje_activo_existente:
            # Si no hay ninguno activo, o si es el primer personaje, hacerlo activo.
            cursor.execute("SELECT 1 FROM Personajes WHERE id_usuario_discord = ?", (id_usuario_discord,))
            if not cursor.fetchone(): # Es el primer personaje
                hacer_este_activo = 1
            # Si ya existen otros pero ninguno activo, también lo hacemos activo
            # (esto es opcional, podrías requerir un comando !activar explícito)
            elif not personaje_activo_existente:
                hacer_este_activo = 1


        cursor.execute("""
            INSERT INTO Personajes (
                id_usuario_discord, nombre_personaje, raza, clase, nivel, 
                trasfondo, alineamiento,
                puntos_golpe_maximos, puntos_golpe_actuales, clase_armadura, personaje_activo,
                bono_competencia /* Añadir más campos con DEFAULT si es necesario */
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (id_usuario_discord, nombre_personaje, raza, clase, nivel,
              trasfondo, alineamiento,
              max_hp, max_hp, ca, hacer_este_activo,
              2 + ((nivel-1)//4) # Cálculo simple de bono de competencia
              ))
        conn.commit()
        personaje_id = cursor.lastrowid
        logging.info(f"Personaje '{nombre_personaje}' (ID: {personaje_id}) registrado para el usuario {id_usuario_discord}.")
        return personaje_id, hacer_este_activo
    except sqlite3.IntegrityError:
        logging.warning(f"El usuario {id_usuario_discord} ya tiene un personaje llamado '{nombre_personaje}'.")
        return None, 0
    except sqlite3.Error as e:
        logging.error(f"Error al registrar personaje '{nombre_personaje}' para {id_usuario_discord}: {e}", exc_info=True)
        return None, 0
    finally:
        if conn:
            conn.close()

def obtener_personaje_activo(id_usuario_discord: str):
    """Obtiene el personaje marcado como activo para el usuario."""
    conn = None
    try:
        conn = obtener_conexion_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Personajes WHERE id_usuario_discord = ? AND personaje_activo = 1", (id_usuario_discord,))
        personaje = cursor.fetchone()
        return dict(personaje) if personaje else None
    except sqlite3.Error as e:
        logging.error(f"Error al obtener personaje activo para {id_usuario_discord}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()

def obtener_personaje_por_nombre(id_usuario_discord: str, nombre_personaje: str):
    """Obtiene un personaje específico por nombre para el usuario."""
    conn = None
    try:
        conn = obtener_conexion_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Personajes WHERE id_usuario_discord = ? AND lower(nombre_personaje) = lower(?)", (id_usuario_discord, nombre_personaje.strip()))
        personaje = cursor.fetchone()
        return dict(personaje) if personaje else None
    except sqlite3.Error as e:
        logging.error(f"Error al obtener personaje '{nombre_personaje}' para {id_usuario_discord}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()

def listar_personajes_usuario(id_usuario_discord: str):
    """Lista todos los personajes de un usuario."""
    conn = None
    try:
        conn = obtener_conexion_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT nombre_personaje, personaje_activo FROM Personajes WHERE id_usuario_discord = ?", (id_usuario_discord,))
        personajes = cursor.fetchall()
        return [dict(p) for p in personajes]
    except sqlite3.Error as e:
        logging.error(f"Error al listar personajes para {id_usuario_discord}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()

def actualizar_hp_personaje(id_personaje: int, nuevos_hp_actuales: int):
    """Actualiza los HP actuales de un personaje por su ID."""
    conn = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()

        cursor.execute("SELECT puntos_golpe_maximos FROM Personajes WHERE id_personaje = ?", (id_personaje,))
        resultado = cursor.fetchone()
        if not resultado:
            logging.warning(f"No se encontró el personaje con ID {id_personaje} para actualizar HP.")
            return False, 0

        max_hp_personaje = resultado[0]
        hp_final = max(0, min(nuevos_hp_actuales, max_hp_personaje))

        cursor.execute("""
            UPDATE Personajes 
            SET puntos_golpe_actuales = ? 
            WHERE id_personaje = ?
        """, (hp_final, id_personaje))
        conn.commit()

        if cursor.rowcount > 0:
            logging.info(f"HP del personaje ID {id_personaje} actualizados a {hp_final}.")
            return True, hp_final
        return False, 0 # No se actualizó (no debería pasar si la query anterior funcionó)
    except sqlite3.Error as e:
        logging.error(f"Error al actualizar HP para personaje ID {id_personaje}: {e}", exc_info=True)
        return False, 0
    finally:
        if conn:
            conn.close()

def activar_personaje(id_usuario_discord: str, nombre_personaje_a_activar: str):
    """Activa un personaje para el usuario y desactiva los demás."""
    conn = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        # Desactivar todos los personajes del usuario
        cursor.execute("UPDATE Personajes SET personaje_activo = 0 WHERE id_usuario_discord = ?", (id_usuario_discord,))
        # Activar el personaje especificado
        cursor.execute("UPDATE Personajes SET personaje_activo = 1 WHERE id_usuario_discord = ? AND lower(nombre_personaje) = lower(?)",
                       (id_usuario_discord, nombre_personaje_a_activar.strip()))
        conn.commit()
        if cursor.rowcount > 0:
            logging.info(f"Personaje '{nombre_personaje_a_activar}' activado para usuario {id_usuario_discord}.")
            return True
        else:
            logging.warning(f"No se pudo activar '{nombre_personaje_a_activar}' para {id_usuario_discord}. No encontrado.")
            return False
    except sqlite3.Error as e:
        logging.error(f"Error al activar personaje para {id_usuario_discord}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            conn.close()

# --- Funciones para RegistroHistoria ---
def anadir_evento_historia(id_canal_discord: str, resumen_evento: str, id_usuario_narrador: str = None, personajes_implicados: str = None, etiquetas: str = None):
    """Añade un nuevo evento al registro de historia de un canal."""
    conn = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO RegistroHistoria (id_canal_discord, resumen_evento, id_usuario_narrador, personajes_implicados, etiquetas, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (id_canal_discord, resumen_evento, id_usuario_narrador, personajes_implicados, etiquetas, datetime.now()))
        conn.commit()
        evento_id = cursor.lastrowid
        logging.info(f"Evento (ID: {evento_id}) añadido al canal {id_canal_discord}: '{resumen_evento[:50]}...'")
        return evento_id
    except sqlite3.Error as e:
        logging.error(f"Error al añadir evento al canal {id_canal_discord}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()

def obtener_historia_reciente(id_canal_discord: str, limite: int = 5):
    """Obtiene los 'limite' eventos más recientes de la historia de un canal."""
    conn = None
    try:
        conn = obtener_conexion_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id_entrada, timestamp, resumen_evento, id_usuario_narrador, personajes_implicados, etiquetas
            FROM RegistroHistoria 
            WHERE id_canal_discord = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (id_canal_discord, limite))
        eventos = cursor.fetchall()
        return [dict(evento) for evento in eventos]
    except sqlite3.Error as e:
        logging.error(f"Error al obtener historia reciente del canal {id_canal_discord}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()

def editar_personaje_campo(id_personaje: int, campo: str, nuevo_valor):
    """Actualiza un campo específico de un personaje."""
    # Lista blanca de campos permitidos para evitar inyección SQL si 'campo' viene del usuario
    campos_permitidos = [
        "raza", "clase", "subclase", "nivel", "trasfondo", "alineamiento",
        "puntos_golpe_maximos", "puntos_golpe_actuales", "puntos_golpe_temporales",
        "clase_armadura", "velocidad", "fuerza", "destreza", "constitucion",
        "inteligencia", "sabiduria", "carisma", "bono_competencia",
        "inspiracion", "equipo_principal", "notas_personaje"
    ]
    if campo not in campos_permitidos:
        logging.error(f"Intento de actualizar campo no permitido: {campo}")
        return False

    conn = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        # Construir la query de forma segura
        sql = f"UPDATE Personajes SET {campo} = ? WHERE id_personaje = ?"
        cursor.execute(sql, (nuevo_valor, id_personaje))
        conn.commit()
        if cursor.rowcount > 0:
            logging.info(f"Campo '{campo}' del personaje ID {id_personaje} actualizado a '{nuevo_valor}'.")
            return True
        logging.warning(f"No se encontró el personaje con ID {id_personaje} para actualizar campo '{campo}'.")
        return False
    except sqlite3.Error as e:
        logging.error(f"Error al actualizar campo '{campo}' para personaje ID {id_personaje}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            conn.close()

def eliminar_personaje_db(id_personaje: int):
    """Elimina un personaje de la base de datos por su ID."""
    conn = None
    try:
        conn = obtener_conexion_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Personajes WHERE id_personaje = ?", (id_personaje,))
        conn.commit()
        if cursor.rowcount > 0:
            logging.info(f"Personaje con ID {id_personaje} eliminado de la base de datos.")
            return True
        logging.warning(f"No se encontró personaje con ID {id_personaje} para eliminar.")
        return False
    except sqlite3.Error as e:
        logging.error(f"Error al eliminar personaje ID {id_personaje}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            conn.close()
