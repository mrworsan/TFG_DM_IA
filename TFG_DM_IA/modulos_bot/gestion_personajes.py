import discord
from discord.ext import commands
import logging  # Es buena práctica añadir logging también a los cogs
import json
import asyncio
import os


# Asumimos que db_utils será accesible a través de self.bot.db_utils
# como se configuró en bot_core.py

class GestionPersonajes(commands.Cog, name="Gestión de Personajes"):
    def __init__(self, bot):
        self.bot = bot
        # self.db = self.bot.db_utils # db_utils se accede a través de self.bot.db_utils

    @commands.Cog.listener()
    async def on_ready(self):
        # Este evento se dispara cuando este Cog específico está listo.
        # Puede ser útil para logging específico del Cog.
        logging.info(f"Módulo '{self.__class__.__name__}' cargado y listo.")

    @commands.command(name='crear_personaje',
                      aliases=['crear'],
                      help='Crea un nuevo personaje. Uso: !crear_personaje <nombre_personaje>')
    async def crear_personaje(self, ctx: commands.Context, *, nombre_personaje: str = None):
        """
        Crea un nuevo personaje para el usuario que ejecuta el comando.
        """
        if not nombre_personaje:
            await ctx.send("Debes proporcionar un nombre para tu personaje. Uso: `!crear_personaje <nombre_personaje>`")
            return

        user_id_str = str(ctx.author.id)  # Asegurarse que es string para la BD si así se definió
        # user_name_discord = ctx.author.name # Nombre de Discord del usuario

        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            json_path = os.path.join(base_dir, 'data', 'creacionpersonajes.json')
            with open(json_path, encoding='utf-8') as f:
                creacion_cfg = json.load(f).get('creacion_personaje', {})

            pasos = creacion_cfg.get('pasos', [])
            atributos_nombres = creacion_cfg.get('atributos', [])
            componentes = creacion_cfg.get('componentes', {})

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            async def obtener_respuesta(mensaje, convert_func=None):
                await ctx.send(mensaje)
                try:
                    resp = await self.bot.wait_for('message', check=check, timeout=120)
                except asyncio.TimeoutError:
                    await ctx.send('Tiempo agotado. Creación cancelada.')
                    raise asyncio.CancelledError()
                contenido = resp.content.strip()
                if contenido.lower() == 'cancelar':
                    await ctx.send('Creación cancelada.')
                    raise asyncio.CancelledError()
                if convert_func:
                    try:
                        return convert_func(contenido)
                    except Exception:
                        await ctx.send('Entrada no válida. Creación cancelada.')
                        raise asyncio.CancelledError()
                return contenido

            await ctx.send(f"Comenzando creación de '{nombre_personaje.strip()}'. Responde a cada pregunta o escribe 'cancelar' para salir.")

            concepto = await obtener_respuesta(f"Paso 1: {pasos[0]}\n{componentes.get('concepto','')}\nDescribe tu personaje:")

            def parse_atributos(texto):
                valores = [int(x) for x in texto.replace(',', ' ').split()]
                if len(valores) != 6:
                    raise ValueError('Se requieren 6 valores')
                return valores

            atributos = await obtener_respuesta(
                f"Paso 2: {pasos[1]}\nIntroduce los valores numéricos de {', '.join(atributos_nombres)} separados por espacios:",
                convert_func=parse_atributos)

            raza = await obtener_respuesta(f"Paso 3: {pasos[2]}\nIndica la raza de tu personaje:")
            clase = await obtener_respuesta(f"Paso 4: {pasos[3]}\nIndica la clase o profesión de tu personaje:")
            ventajas = await obtener_respuesta(f"Paso 5: {pasos[4]}")
            habilidades = await obtener_respuesta(f"Paso 6: {pasos[5]}")
            hp_max = await obtener_respuesta(f"Paso 7: {pasos[6]}\n¿Cuántos puntos de vida máximos tiene tu personaje?", int)
            equipo = await obtener_respuesta(f"Paso 8: {pasos[7]}")

            personaje_id, fue_activado = await self.bot.loop.run_in_executor(
                None,
                self.bot.db_utils.registrar_personaje,
                user_id_str,
                nombre_personaje.strip(),
                raza.strip(),
                clase.strip(),
                1,
                hp_max,
                10,
                None,
                None,
            )

            if not personaje_id:
                await ctx.send(f"Hubo un problema al crear el personaje '{nombre_personaje.strip()}'. Puede que ya exista uno con ese nombre.")
                return

            campos_extra = {
                'fuerza': atributos[0],
                'destreza': atributos[1],
                'constitucion': atributos[2],
                'inteligencia': atributos[3],
                'sabiduria': atributos[4],
                'carisma': atributos[5],
                'puntos_golpe_maximos': hp_max,
                'puntos_golpe_actuales': hp_max,
                'equipo_principal': equipo,
                'notas_personaje': f"Concepto: {concepto}\nVentajas y desventajas: {ventajas}\nHabilidades: {habilidades}",
            }

            for campo, valor in campos_extra.items():
                await self.bot.loop.run_in_executor(None, self.bot.db_utils.editar_personaje_campo, personaje_id, campo, valor)

            if fue_activado:
                await ctx.send(f"¡Personaje '{nombre_personaje.strip()}' creado y activado con éxito para {ctx.author.mention}!")
            else:
                await ctx.send(f"¡Personaje '{nombre_personaje.strip()}' creado con éxito para {ctx.author.mention}! Ya tienes otro personaje activo. Puedes usar `!activar_personaje {nombre_personaje.strip()}` si quieres.")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.error(f"Error en !crear_personaje para {ctx.author.name}: {e}", exc_info=True)
            await ctx.send(f"Lo siento {ctx.author.mention}, ocurrió un error al intentar crear tu personaje.")

    @commands.command(name='ficha', aliases=['sheet', 'personaje'], help='Muestra la ficha de tu personaje activo.')
    async def ver_ficha_personaje(self, ctx: commands.Context):
        """
        Muestra la información del personaje activo del usuario.
        """
        user_id_str = str(ctx.author.id)

        try:
            personaje_data = await self.bot.loop.run_in_executor(None, self.bot.db_utils.obtener_personaje_activo,
                                                                 user_id_str)  #

            if personaje_data:
                # Campos a mostrar y sus etiquetas amigables
                campos_mostrar = {
                    "nombre_personaje": "Nombre",
                    "raza": "Raza", "clase": "Clase", "subclase": "Subclase",
                    "nivel": "Nivel", "trasfondo": "Trasfondo", "alineamiento": "Alineamiento",
                    "puntos_golpe_actuales": "PG Actuales", "puntos_golpe_maximos": "PG Máximos",
                    "puntos_golpe_temporales": "PG Temporales", "clase_armadura": "CA",
                    "velocidad": "Velocidad",
                    "fuerza": "FUE", "destreza": "DES", "constitucion": "CON",
                    "inteligencia": "INT", "sabiduria": "SAB", "carisma": "CAR",
                    "bono_competencia": "Bono Competencia", "inspiracion": "Inspiración",
                    "equipo_principal": "Equipo Principal", "notas_personaje": "Notas"
                }

                # Crear un Embed de Discord
                embed = discord.Embed(
                    title=f"Ficha de {personaje_data.get('nombre_personaje', 'Personaje Desconocido')} (Activo)",
                    color=discord.Color.blue()  # Puedes elegir el color que prefieras
                )
                embed.set_thumbnail(url=ctx.author.display_avatar.url)  # Avatar del usuario

                for key, display_name in campos_mostrar.items():
                    valor = personaje_data.get(key)
                    if valor is not None and str(valor).strip() != '':  # Mostrar si no es None y no es cadena vacía
                        embed.add_field(name=display_name, value=str(valor),
                                        inline=True)  # inline=True para múltiples campos por línea

                # Asegurar que los campos de atributos se muestren en un orden lógico si es posible
                # (el orden de add_field importa para la visualización en columnas)

                await ctx.send(embed=embed)

            else:
                await ctx.send(
                    f"{ctx.author.mention}, no tienes ningún personaje activo. Puedes crear uno con `!crear_personaje <nombre>` o activar uno existente con `!activar_personaje <nombre>`.")

        except Exception as e:
            logging.error(f"Error al procesar el comando !ficha para {ctx.author.name}: {e}", exc_info=True)
            await ctx.send(
                f"Lo siento {ctx.author.mention}, ocurrió un error al intentar mostrar tu ficha de personaje.")

    @commands.command(name='activar_personaje', aliases=['activar'],
                      help='Activa uno de tus personajes. Uso: !activar_personaje <nombre_personaje>')
    async def activar_personaje_cmd(self, ctx: commands.Context, *, nombre_personaje: str = None):
        """
        Establece un personaje específico como el activo para el usuario.
        """
        if not nombre_personaje:
            await ctx.send(
                "Debes especificar el nombre del personaje que quieres activar. Uso: `!activar_personaje <nombre_personaje>`")
            return

        user_id_str = str(ctx.author.id)

        try:
            activado_con_exito = await self.bot.loop.run_in_executor(None, self.bot.db_utils.activar_personaje,
                                                                     user_id_str, nombre_personaje.strip())  #

            if activado_con_exito:
                await ctx.send(f"¡Personaje '{nombre_personaje.strip()}' activado con éxito para {ctx.author.mention}!")
            else:
                await ctx.send(
                    f"{ctx.author.mention}, no pude encontrar un personaje llamado '{nombre_personaje.strip()}' en tu lista o hubo un error al activarlo.")

        except Exception as e:
            logging.error(f"Error al procesar el comando !activar_personaje para {ctx.author.name}: {e}", exc_info=True)
            await ctx.send(f"Lo siento {ctx.author.mention}, ocurrió un error al intentar activar el personaje.")

    @commands.command(name='mis_personajes', aliases=['personajes', 'listpj'],
                      help='Muestra una lista de tus personajes creados.')
    async def mis_personajes_cmd(self, ctx: commands.Context):
        """
        Muestra todos los personajes registrados por el usuario.
        """
        user_id_str = str(ctx.author.id)

        try:
            lista_personajes_data = await self.bot.loop.run_in_executor(None,
                                                                        self.bot.db_utils.listar_personajes_usuario,
                                                                        user_id_str)  #

            if lista_personajes_data:
                embed = discord.Embed(
                    title=f"Personajes de {ctx.author.display_name}",
                    color=discord.Color.green()
                )
                embed.set_thumbnail(url=ctx.author.display_avatar.url)

                description_text = ""
                for p_data in lista_personajes_data:
                    nombre = p_data.get('nombre_personaje', 'Nombre Desconocido')
                    es_activo = p_data.get('personaje_activo', 0)
                    indicador_activo = " ⭐ (Activo)" if es_activo == 1 else ""
                    description_text += f"- **{nombre}**{indicador_activo}\n"

                embed.description = description_text if description_text else "No se encontraron personajes."
                await ctx.send(embed=embed)
            else:
                await ctx.send(
                    f"{ctx.author.mention}, aún no has creado ningún personaje. Usa `!crear_personaje <nombre>`.")

        except Exception as e:
            logging.error(f"Error al procesar el comando !mis_personajes para {ctx.author.name}: {e}", exc_info=True)
            await ctx.send(f"Lo siento {ctx.author.mention}, ocurrió un error al intentar listar tus personajes.")

    @commands.command(name='set_hp', aliases=['hp'],
                      help='Establece los HP actuales de tu personaje activo. Uso: !set_hp <valor>')
    async def set_hp_cmd(self, ctx: commands.Context, nuevo_hp_str: str = None):
        """
        Actualiza los HP actuales del personaje activo del usuario.
        """
        if nuevo_hp_str is None:
            await ctx.send("Debes proporcionar un valor para los HP. Uso: `!set_hp <número>`")
            return

        user_id_str = str(ctx.author.id)

        try:
            nuevo_hp = int(nuevo_hp_str)
        except ValueError:
            await ctx.send("El valor de HP debe ser un número entero. Uso: `!set_hp <número>`")
            return

        try:
            personaje_activo = await self.bot.loop.run_in_executor(None, self.bot.db_utils.obtener_personaje_activo,
                                                                   user_id_str)  #

            if not personaje_activo:
                await ctx.send(
                    f"{ctx.author.mention}, no tienes un personaje activo. Crea uno o usa `!activar_personaje <nombre>`.")
                return

            id_personaje = personaje_activo.get('id_personaje')
            nombre_pj_activo = personaje_activo.get('nombre_personaje', 'Tu personaje activo')
            max_hp_personaje = personaje_activo.get('puntos_golpe_maximos')

            if not id_personaje:
                logging.error(
                    f"No se pudo obtener el ID del personaje activo para {user_id_str} al intentar usar !set_hp.")
                await ctx.send("Error interno: No se pudo obtener el ID de tu personaje activo.")
                return

            # La función actualizar_hp_personaje ya maneja el cap a max_hp y >= 0
            actualizado, hp_final = await self.bot.loop.run_in_executor(None, self.bot.db_utils.actualizar_hp_personaje,
                                                                        id_personaje, nuevo_hp)  #

            if actualizado:
                await ctx.send(
                    f"HP de '{nombre_pj_activo}' actualizados a {hp_final}/{max_hp_personaje if max_hp_personaje is not None else 'N/A'}.")
            else:
                # Esto podría pasar si el personaje no se encuentra en actualizar_hp_personaje, aunque obtener_personaje_activo ya lo verificó.
                await ctx.send(
                    f"No se pudieron actualizar los HP de '{nombre_pj_activo}'. Verifica que el personaje exista.")

        except Exception as e:
            logging.error(f"Error al procesar el comando !set_hp para {ctx.author.name}: {e}", exc_info=True)
            await ctx.send(f"Lo siento {ctx.author.mention}, ocurrió un error al intentar actualizar los HP.")

    @commands.command(name='escribir_diario', aliases=['diario'],
                      help='Escribe una entrada en el diario de tu personaje activo. Uso: !escribir_diario <texto>')
    async def escribir_diario_cmd(self, ctx: commands.Context, *, texto_nota: str = None):
        """Actualiza el campo de notas del personaje activo del usuario."""
        if not texto_nota:
            await ctx.send("Debes proporcionar el texto para el diario. Uso: `!escribir_diario <texto>`")
            return

        user_id_str = str(ctx.author.id)

        try:
            personaje_activo = await self.bot.loop.run_in_executor(None, self.bot.db_utils.obtener_personaje_activo,
                                                                   user_id_str)
            if not personaje_activo:
                await ctx.send(f"{ctx.author.mention}, no tienes un personaje activo. Crea uno o usa `!activar_personaje <nombre>`.")
                return

            id_personaje = personaje_activo.get('id_personaje')
            nombre_pj_activo = personaje_activo.get('nombre_personaje', 'Tu personaje activo')

            actualizado = await self.bot.loop.run_in_executor(None, self.bot.db_utils.editar_personaje_campo,
                                                              id_personaje, 'notas_personaje', texto_nota.strip())

            if actualizado:
                await ctx.send(f"El diario de '{nombre_pj_activo}' ha sido actualizado.")
            else:
                await ctx.send(f"No se pudieron actualizar las notas de '{nombre_pj_activo}'. Verifica que el personaje exista.")

        except Exception as e:
            logging.error(f"Error al procesar el comando !escribir_diario para {ctx.author.name}: {e}", exc_info=True)
            await ctx.send(f"Lo siento {ctx.author.mention}, ocurrió un error al intentar escribir en el diario.")

    @commands.command(name='leer_diario', aliases=['ver_diario'],
                      help='Muestra las notas del diario de tu personaje activo.')
    async def leer_diario_cmd(self, ctx: commands.Context):
        """Envía al usuario el contenido del diario de su personaje activo."""
        user_id_str = str(ctx.author.id)

        try:
            personaje_activo = await self.bot.loop.run_in_executor(None, self.bot.db_utils.obtener_personaje_activo,
                                                                   user_id_str)
            if not personaje_activo:
                await ctx.send(f"{ctx.author.mention}, no tienes un personaje activo. Crea uno o usa `!activar_personaje <nombre>`.")
                return

            nombre_pj_activo = personaje_activo.get('nombre_personaje', 'Tu personaje activo')
            notas_diario = personaje_activo.get('notas_personaje')

            if notas_diario and str(notas_diario).strip():
                embed = discord.Embed(title=f"Diario de {nombre_pj_activo}", description=str(notas_diario),
                                      color=discord.Color.purple())
                embed.set_thumbnail(url=ctx.author.display_avatar.url)
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"{ctx.author.mention}, el diario de '{nombre_pj_activo}' está vacío.")

        except Exception as e:
            logging.error(f"Error al procesar el comando !leer_diario para {ctx.author.name}: {e}", exc_info=True)
            await ctx.send(f"Lo siento {ctx.author.mention}, ocurrió un error al intentar leer el diario.")


async def setup(bot: commands.Bot):
    # Asegurarse de que db_utils está disponible en el bot antes de añadir el Cog
    if not hasattr(bot, 'db_utils') or bot.db_utils is None:  #
        logging.error(
            "CRITICAL: db_utils no encontrado en el objeto bot al intentar cargar GestionPersonajes. Este Cog no se cargará.")
        return

    await bot.add_cog(GestionPersonajes(bot))
    logging.info("Cog 'GestionPersonajes' añadido al bot.")
