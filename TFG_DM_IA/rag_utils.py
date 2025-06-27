# TFG_DM_IA/rag_utils.py
import logging
import time
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os
import pickle
import json
import glob
from datasets import load_dataset  # <--- AÑADIDO PARA FIREBALL

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FOLDER_PATH = os.path.join(BASE_DIR, "data")

EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2'  # Modelo más ligero y rápido
INDEX_FILE_PATH = os.path.join(DATA_FOLDER_PATH, "faiss_index_v5_with_fireball.idx")  # Nuevo nombre de índice
DOCUMENTS_FILE_PATH = os.path.join(DATA_FOLDER_PATH, "indexed_documents_v5_with_fireball.pkl")  # Nuevo nombre de docs

embedding_model = None
faiss_index = None
indexed_docs = None


def get_embedding_model():
    global embedding_model
    if embedding_model is None:
        logging.info(f"Cargando modelo de embeddings: {EMBEDDING_MODEL_NAME}...")
        try:
            embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
            logging.info("Modelo de embeddings cargado.")
        except Exception as e:
            logging.error(f"Error al cargar el modelo de embeddings: {e}", exc_info=True)
            embedding_model = None
    return embedding_model


def _clean_text(text_input):
    if text_input is None: return ""
    if not isinstance(text_input, str):
        if isinstance(text_input, (list, tuple)):
            # Si es una lista de diccionarios (como a veces en "items" de equipo inicial)
            if all(isinstance(item, dict) for item in text_input):
                dict_strs = []
                for item_dict in text_input:
                    item_parts = []
                    for k_item, v_item in item_dict.items():
                        # Evitar recursión infinita si v_item es la misma lista
                        if v_item is text_input:
                            item_parts.append(f"{_clean_text(k_item)}: <recursive_data_omitted>")
                        else:
                            item_parts.append(f"{_clean_text(k_item)}: {_clean_text(v_item)}")
                    dict_strs.append("{ " + ", ".join(item_parts) + " }")
                text_input = ", ".join(dict_strs)
            else:  # Lista de strings u otros tipos simples
                text_input = ", ".join(map(str, text_input))

        elif isinstance(text_input, dict):
            try:
                text_input = ". ".join(
                    [f"{k.replace('_', ' ').capitalize()}: {_clean_text(v)}" for k, v in text_input.items() if
                     v is not None])
            except Exception as e:  # Captura errores más específicos si es necesario
                logging.debug(f"Error limpiando diccionario, usando json.dumps: {e}")
                text_input = json.dumps(text_input, ensure_ascii=False)
        else:
            text_input = str(text_input)
    return text_input.replace('\n', ' ').replace('\r', ' ').replace('  ', ' ').strip()


def _format_document(prefix, name, description_content_list):
    name_cleaned = _clean_text(name) if name else "Información General"
    valid_desc_parts = [_clean_text(part) for part in description_content_list if part]
    description_cleaned = ". ".join(filter(None, valid_desc_parts))

    if not description_cleaned and name_cleaned == "Información General": return None

    # Construir el documento con el prefijo y el nombre claramente visibles
    # y luego la descripción.
    if not description_cleaned and name:
        # Si no hay descripción pero sí un nombre, el documento es solo el prefijo y el nombre.
        return f"{_clean_text(prefix)} - {_clean_text(name)}."

    # Si hay descripción, incluirla.
    return f"{_clean_text(prefix)} - {_clean_text(name)}: {description_cleaned}"


def _extract_details_as_string(item_data, fields_map):
    parts = []
    if not isinstance(item_data, dict): return ""
    for field, display_name in fields_map.items():
        value = item_data.get(field)
        if value is not None:
            cleaned_value = _clean_text(value)
            if field == "components" and not cleaned_value:  # Manejo especial para componentes vacíos
                parts.append(f"{display_name}: Ninguno")
            # Asegurarse de que el valor limpiado no esté vacío o sea solo espacios,
            # o que el valor original sea booleano, entero o flotante (que _clean_text convertiría a string).
            elif cleaned_value or isinstance(value, (bool, int, float)):
                parts.append(f"{display_name}: {cleaned_value}")
    return ". ".join(parts)


def _process_generic_item(item_dict, default_prefix, name_key="nombre", desc_keys=None, details_map=None):
    if not isinstance(item_dict, dict): return None
    name = item_dict.get(name_key) or item_dict.get("name") or item_dict.get("term")

    desc_parts = []

    # Prioridad a desc_keys si se proveen, sino usar una lista genérica
    effective_desc_keys = desc_keys if desc_keys is not None else ["descripcion", "description", "definition", "efecto",
                                                                   "descripcion_general"]

    main_description_found = False
    for dk in effective_desc_keys:
        desc_val = item_dict.get(dk)
        if desc_val:  # Si encuentra una descripción, la usa y para.
            cleaned_desc_val = _clean_text(desc_val)
            if cleaned_desc_val:  # Solo añadir si no está vacía después de limpiar
                desc_parts.append(cleaned_desc_val)
                main_description_found = True
                break

                # Si no se encontró descripción principal pero hay un nombre, usar el nombre como descripción.
    if not main_description_found and name:
        desc_parts.append(f"Este es un registro para '{_clean_text(name)}'.")

    if details_map and isinstance(details_map, dict):
        extracted_details = _extract_details_as_string(item_dict, details_map)
        if extracted_details:
            # Añadir como una parte más de la descripción general, no reemplazar.
            desc_parts.append(f"Detalles adicionales: {extracted_details}")

    # Si después de todo, desc_parts está vacío y no hay nombre, no se puede generar el documento.
    if not name and not any(dp.strip() for dp in desc_parts if dp): return None

    return _format_document(default_prefix, name, desc_parts)


# --- Funciones de procesamiento específicas (ya las tienes, las incluyo por completitud) ---

def _process_origenes_file(origenes_data):  #
    docs = []
    if not isinstance(origenes_data, dict) or "trasfondos" not in origenes_data:
        logging.warning("Formato de Origenes.json no esperado en _process_origenes_file.")
        return docs

    regla_puntuaciones_general = origenes_data.get("regla_puntuaciones_habilidad",
                                                   "Se sugiere aumentar una de estas puntuaciones en +2 y otra en +1, O aumentar las tres en +1, sin superar 20.")

    for item_dict in origenes_data.get("trasfondos", []):
        if not isinstance(item_dict, dict):
            continue
        origen_name = item_dict.get("nombre", "Origen Desconocido")
        desc_parts_origen = [
            f"Información sobre el Origen/Trasfondo de Dungeons & Dragons: '{_clean_text(origen_name)}'."]
        if item_dict.get("descripcion"): desc_parts_origen.append(
            f"Descripción: {_clean_text(item_dict.get('descripcion'))}")
        if item_dict.get("puntuaciones_habilidad"):
            habilidades_sugeridas = ", ".join(item_dict.get('puntuaciones_habilidad', []))
            desc_parts_origen.append(
                f"Puntuaciones de Habilidad Sugeridas para {origen_name}: {habilidades_sugeridas}.")
            desc_parts_origen.append(
                f"Regla de Asignación General para Puntuaciones de Origen: {_clean_text(regla_puntuaciones_general)}")
        if item_dict.get("dote"): desc_parts_origen.append(f"Dote Sugerida: {_clean_text(item_dict.get('dote'))}.")
        if item_dict.get("competencias_habilidades"):
            competencias_habilidades_str = ", ".join(item_dict.get('competencias_habilidades', []))
            desc_parts_origen.append(f"Competencias en Habilidades Otorgadas: {competencias_habilidades_str}.")
        if item_dict.get("competencia_herramientas"):
            competencia_herramientas_data = item_dict.get('competencia_herramientas')
            competencia_herramientas_str = _clean_text(competencia_herramientas_data) if not isinstance(
                competencia_herramientas_data, list) else ", ".join(competencia_herramientas_data)
            desc_parts_origen.append(f"Competencia en Herramientas Otorgada: {competencia_herramientas_str}.")
        if item_dict.get("equipo"):
            equipo_parts_list = []
            for opcion_idx, opcion_equipo in enumerate(item_dict.get("equipo", [])):
                if isinstance(opcion_equipo, dict):
                    if opcion_equipo.get("opcion") and opcion_equipo.get("items"):
                        equipo_parts_list.append(
                            f"Opción {opcion_equipo.get('opcion')}: {', '.join(opcion_equipo.get('items', []))}.")
                    elif opcion_equipo.get("oro") and opcion_equipo.get("unidad_moneda"):
                        equipo_parts_list.append(
                            f"Alternativamente: {opcion_equipo.get('oro')} {opcion_equipo.get('unidad_moneda')}.")
                    elif opcion_equipo.get("items"):
                        equipo_parts_list.append(
                            f"Opción {chr(65 + opcion_idx)}: {', '.join(opcion_equipo.get('items', []))}.")
            if equipo_parts_list: desc_parts_origen.append("Equipo Inicial: " + " ".join(equipo_parts_list))
        if item_dict.get("referencia"): desc_parts_origen.append(
            f"Referencia Manual: {_clean_text(item_dict.get('referencia'))}.")
        doc_completo_origen = _format_document("Origen", origen_name, desc_parts_origen)
        if doc_completo_origen: docs.append(doc_completo_origen)
    return docs


def _process_spell(spell_data):  #
    if not isinstance(spell_data, dict): return []
    name_en = spell_data.get("name")
    name_es = spell_data.get("nombre_esp")
    display_name_primary = name_es if name_es else name_en
    if not display_name_primary:
        logging.warning("Hechizo sin 'name' ni 'nombre_esp' en Spell.json, saltando.")
        return []
    name_cleaned_for_title = _clean_text(display_name_primary)
    desc_parts = []
    if name_es: desc_parts.append(f"Nombre del hechizo (Español): {_clean_text(name_es)}.")
    if name_en and (not name_es or (_clean_text(name_en).lower() != _clean_text(name_es).lower())): desc_parts.append(
        f"Nombre original (Inglés): {_clean_text(name_en)}.")
    level = spell_data.get('level', 'desconocido')
    school_raw = spell_data.get('school_esp') or spell_data.get('school')
    school_cleaned = _clean_text(school_raw)
    intro_sentence = f"El hechizo de Dungeons & Dragons '{name_cleaned_for_title}' es un conjuro de nivel {level}"
    if school_cleaned:
        intro_sentence += f" de la escuela de magia '{school_cleaned}'."
    else:
        intro_sentence += "."
    desc_parts.append(intro_sentence)
    main_description_raw = spell_data.get("description_esp") or spell_data.get("description")
    if main_description_raw and _clean_text(main_description_raw):
        desc_parts.append(f"Descripción del efecto: {_clean_text(main_description_raw)}")
    else:
        desc_parts.append(
            f"El hechizo {name_cleaned_for_title} no tiene una descripción detallada de su efecto principal.")
    details_map = {"casting_time": "Tiempo de Lanzamiento", "range": "Alcance", "components": "Componentes",
                   "duration": "Duración", "source": "Fuente del Manual"}
    extracted_details_str = _extract_details_as_string(spell_data, details_map)
    if extracted_details_str: desc_parts.append(f"Otros detalles: {extracted_details_str}")
    higher_levels_desc_raw = spell_data.get("higher_levels_esp") or spell_data.get("higher_levels")
    if higher_levels_desc_raw and _clean_text(higher_levels_desc_raw): desc_parts.append(
        f"A niveles superiores: {_clean_text(higher_levels_desc_raw)}")
    formatted_doc = _format_document("Hechizo", name_cleaned_for_title, desc_parts)
    return [formatted_doc] if formatted_doc else []


def _process_rule(rule_data):  #
    term = rule_data.get("term")
    definition = rule_data.get("definition")
    if not term: return []
    desc_parts = [
        f"La regla o término de Dungeons & Dragons '{_clean_text(term)}' se define como: {_clean_text(definition)}."]
    if "details" in rule_data and isinstance(rule_data["details"], dict): desc_parts.append(
        f"Detalles adicionales para '{_clean_text(term)}': {_clean_text(rule_data['details'])}")
    return [_format_document("Regla D&D", term, desc_parts)]


def _process_class_file(class_data, filename_for_default_name):  #
    docs = []
    class_name_main = class_data.get("clase", os.path.basename(filename_for_default_name).replace(".json", ""))
    prefix_base = f"Clase {class_name_main}"
    if class_data.get("descripcion_general"): docs.append(
        _format_document(prefix_base, "Descripción General", [class_data["descripcion_general"]]))
    if isinstance(class_data.get("rasgos_principales"), dict):
        rp_details = _extract_details_as_string(class_data["rasgos_principales"],
                                                {k: k.replace('_', ' ').capitalize() for k in
                                                 class_data["rasgos_principales"]})
        if rp_details: docs.append(_format_document(prefix_base, "Resumen de Rasgos Principales", [rp_details]))
    if isinstance(class_data.get("detalles_rasgos_clase"), dict):
        for trait_name, trait_details in class_data["detalles_rasgos_clase"].items():
            if isinstance(trait_details, dict):
                desc_trait = [trait_details.get("descripcion"), f"Nivel: {trait_details.get('nivel', 'N/A')}"]
                desc_trait.append(_extract_details_as_string(trait_details, {"efectos_iniciales": "Efectos Iniciales",
                                                                             "efectos_nuevos": "Nuevos Efectos",
                                                                             "referencia": "Ref."}))
                docs.append(_format_document(f"{prefix_base} - Rasgo", trait_name, desc_trait))
    if isinstance(class_data.get("subclases"), list):
        for subclass_dict in class_data["subclases"]:
            if isinstance(subclass_dict, dict):
                subclass_name = subclass_dict.get("nombre", "Desconocida")
                subclass_prefix = f"{prefix_base} - Subclase {subclass_name}"
                sub_desc_parts = [f"Información sobre la subclase '{subclass_name}' de la clase {class_name_main}."]
                if subclass_dict.get("descripcion"): sub_desc_parts.append(subclass_dict.get("descripcion"))
                conjuros_keys = ["conjuros_patron", "conjuros_juramento", "conjuros_dominio", "conjuros_circulo",
                                 "conjuros_psionicos", "conjuros_relojeria", "conjuros_draconicos",
                                 "conjuros_del_errante_feérico", "conjuros_del_acechador_en_la_penumbra",
                                 "conjuros_adicionales", "conjuros_de_dominio"]
                for conj_key in conjuros_keys:
                    if conj_key in subclass_dict and subclass_dict[conj_key]: sub_desc_parts.append(
                        f"{conj_key.replace('_', ' ').capitalize()}: {_clean_text(subclass_dict[conj_key])}")
                docs.append(_format_document(subclass_prefix, "Descripción y Conjuros", sub_desc_parts))
                if isinstance(subclass_dict.get("rasgos"), list):
                    for sub_trait_dict in subclass_dict["rasgos"]:
                        if isinstance(sub_trait_dict, dict):
                            trait_name = sub_trait_dict.get("nombre")
                            trait_desc_parts = [sub_trait_dict.get("descripcion"),
                                                f"Nivel: {sub_trait_dict.get('nivel', 'N/A')}"]
                            other_subtrait_details = {k: v for k, v in sub_trait_dict.items() if
                                                      k not in ["nombre", "descripcion", "nivel", "referencia"]}
                            trait_desc_parts.append(_extract_details_as_string(other_subtrait_details,
                                                                               {k: k.replace('_', ' ').capitalize() for
                                                                                k in other_subtrait_details}))
                            docs.append(_format_document(f"{subclass_prefix} - Rasgo", trait_name, trait_desc_parts))
    return [doc for doc in docs if doc]


def _process_species_file(species_data):  #
    docs = []
    if not (isinstance(species_data, dict) and "especies" in species_data and isinstance(species_data["especies"],
                                                                                         list)):
        logging.warning("Formato de species_data no esperado en _process_species_file.")
        return docs
    for especie_dict in species_data["especies"]:
        if not isinstance(especie_dict, dict): continue
        especie_name_base = especie_dict.get("nombre", "Especie Desconocida")
        general_desc_parts = [f"Información general sobre la especie de D&D '{especie_name_base}'."]
        if especie_dict.get("descripcion"): general_desc_parts.append(_clean_text(especie_dict["descripcion"]))
        general_details_map = {"tipo_criatura": "Tipo de Criatura", "tamaño": "Tamaño Promedio",
                               "velocidad": "Velocidad Base", "esperanza_vida": "Esperanza de Vida"}
        extracted_general_details = _extract_details_as_string(especie_dict, general_details_map)
        if extracted_general_details: general_desc_parts.append(extracted_general_details)
        nombres_rasgos_especiales_list = [rasgo.get("nombre") for rasgo in especie_dict.get("rasgos_especiales", []) if
                                          isinstance(rasgo, dict) and rasgo.get("nombre")]
        if nombres_rasgos_especiales_list: general_desc_parts.append(
            f"Rasgos clave: {', '.join(nombres_rasgos_especiales_list)}.")
        formatted_general_doc = _format_document("Especie", especie_name_base, general_desc_parts)
        if formatted_general_doc: docs.append(formatted_general_doc)
        for rasgo_esp_dict in especie_dict.get("rasgos_especiales", []):
            if not isinstance(rasgo_esp_dict, dict): continue
            rasgo_name_original = rasgo_esp_dict.get("nombre")
            rasgo_descripcion_principal = rasgo_esp_dict.get("descripcion")
            option_list_keys_map = {
                "tabla_linajes": ("linaje", "Linaje", ["descripcion", "nivel_1", "nivel_3", "nivel_5"]),
                "opciones_transformacion": ("nombre", "Opción de Transformación de Revelación Celestial", ["efecto"]),
                "opciones_linaje": ("nombre", "Opción de Linaje Gnómico", ["descripcion"]),
                "opciones_don": ("nombre", "Don de Gigante", ["efecto"])
            }
            processed_as_option_list = False
            for opt_key, (opt_name_field, opt_display_prefix, opt_detail_fields_keys) in option_list_keys_map.items():
                if opt_key in rasgo_esp_dict and isinstance(rasgo_esp_dict[opt_key], list):
                    processed_as_option_list = True
                    if rasgo_name_original and rasgo_descripcion_principal: docs.append(
                        _format_document(f"Especie {especie_name_base} - Rasgo Contenedor", rasgo_name_original,
                                         [rasgo_descripcion_principal]))
                    for option_detail_dict in rasgo_esp_dict[opt_key]:
                        if isinstance(option_detail_dict, dict):
                            option_name_val = option_detail_dict.get(opt_name_field)
                            if option_name_val:
                                doc_name_for_option = f"{especie_name_base} ({opt_display_prefix} {option_name_val})"
                                option_desc_parts = [
                                    f"El {opt_display_prefix} '{option_name_val}' es una variante de la especie {especie_name_base}."]
                                if option_name_val.lower() == "drow":
                                    option_desc_parts.append(
                                        "Los Drow, elfos oscuros, están adaptados a la Suboscuridad.")
                                elif option_name_val.lower() == "elfo del bosque":
                                    option_desc_parts.append(
                                        "Los Elfos del Bosque son ágiles y conectados con la naturaleza.")
                                temp_option_details = {k: v for k, v in option_detail_dict.items() if
                                                       k not in [opt_name_field, "referencia"]}
                                option_desc_parts.append(_extract_details_as_string(temp_option_details,
                                                                                    {k: k.replace('_', ' ').capitalize()
                                                                                     for k in temp_option_details}))
                                formatted_option_doc = _format_document(f"Especie {especie_name_base}",
                                                                        doc_name_for_option, option_desc_parts)
                                if formatted_option_doc: docs.append(formatted_option_doc)
                    break
            if not processed_as_option_list and rasgo_name_original and rasgo_descripcion_principal:
                docs.append(_format_document(f"Especie {especie_name_base} - Rasgo", rasgo_name_original,
                                             [rasgo_descripcion_principal]))
    return [doc for doc in docs if doc]


def _process_equipment_file(equip_data):  #
    docs = []
    if "moneda" in equip_data:
        if equip_data["moneda"].get("descripcion"): docs.append(
            _format_document("Equipamiento Moneda", "Descripción General", [equip_data["moneda"]["descripcion"]]))
        if "valores" in equip_data["moneda"]:
            for item in equip_data["moneda"]["valores"]: docs.append(_process_generic_item(item, "Moneda"))
    if "armas" in equip_data:
        if equip_data["armas"].get("descripcion"): docs.append(
            _format_document("Equipamiento Armas", "Descripción General", [equip_data["armas"]["descripcion"]]))
        for prop_type in ["propiedades_estandard", "propiedades_maestria"]:
            if prop_type in equip_data["armas"] and isinstance(equip_data["armas"][prop_type], list):
                prop_display_name = prop_type.split('_')[-1].capitalize()
                for item in equip_data["armas"][prop_type]: docs.append(
                    _process_generic_item(item, f"Propiedad Arma ({prop_display_name})"))
        if "lista_armas" in equip_data["armas"] and isinstance(equip_data["armas"]["lista_armas"], list):
            for item in equip_data["armas"]["lista_armas"]: docs.append(
                _process_generic_item(item, "Arma", desc_keys=["daño"],
                                      details_map={"categoria": "Categoría", "costo": "Costo", "peso": "Peso",
                                                   "propiedades": "Propiedades", "maestria": "Maestría"}))
    if "armaduras" in equip_data:
        if equip_data["armaduras"].get("descripcion"): docs.append(
            _format_document("Equipamiento Armaduras", "Descripción General", [equip_data["armaduras"]["descripcion"]]))
        if "lista_armaduras" in equip_data["armaduras"] and isinstance(equip_data["armaduras"]["lista_armaduras"],
                                                                       list):
            for item in equip_data["armaduras"]["lista_armaduras"]: docs.append(
                _process_generic_item(item, "Armadura", desc_keys=[],
                                      details_map={"categoria": "Categoría", "costo": "Costo", "peso": "Peso",
                                                   "ca_base": "CA Base", "mod_destreza": "Mod Destreza",
                                                   "max_destreza": "Max Destreza", "req_fuerza": "Req Fuerza",
                                                   "sigilo_desv": "Sigilo Desv"}))
    if "herramientas" in equip_data:
        if equip_data["herramientas"].get("descripcion"): docs.append(
            _format_document("Equipamiento Herramientas", "Descripción General",
                             [equip_data["herramientas"]["descripcion"]]))
        for tool_type_key in ["herramientas_artesano", "otras_herramientas"]:
            if tool_type_key in equip_data["herramientas"] and isinstance(equip_data["herramientas"][tool_type_key],
                                                                          list):
                prefix = "Herramienta Artesano" if tool_type_key == "herramientas_artesano" else "Herramienta Otra"
                for item in equip_data["herramientas"][tool_type_key]: docs.append(
                    _process_generic_item(item, prefix, desc_keys=["descripcion_uso_fabricar", "descripcion_uso"],
                                          details_map={"costo": "Costo", "peso": "Peso", "habilidad": "Habilidad",
                                                       "utilizar": "Utilizar", "fabricar": "Fabricar"}))
    if "equipo_aventurero" in equip_data and isinstance(equip_data["equipo_aventurero"], list):
        for item in equip_data["equipo_aventurero"]: docs.append(
            _process_generic_item(item, "Equipo Aventurero", desc_keys=["descripcion"],
                                  details_map={"costo": "Costo", "peso": "Peso"}))
    return [doc for doc in docs if doc]


# --- Nueva función para procesar FIREBALL ---
def _process_fireball_turn(turn_data, turn_index):
    """
    Procesa un turno del dataset FIREBALL para convertirlo en un documento de texto para RAG.
    Nos centraremos en las 'utterances'.
    """
    if not isinstance(turn_data, dict):
        return None

    utterances_texts = []

    # Los campos pueden ser strings o listas de strings.
    # Los normalizamos a listas de strings para un procesamiento uniforme.
    fields_to_process = {
        'before_utterances': turn_data.get('before_utterances', []),
        'message': turn_data.get('message', ""),  # 'message' es la utterance principal del turno
        'after_utterances': turn_data.get('after_utterances', [])
    }

    for field_name, field_content in fields_to_process.items():
        if isinstance(field_content, str):
            if field_content.strip():  # Solo añadir si no está vacío
                utterances_texts.append(_clean_text(field_content))
        elif isinstance(field_content, list):
            for ut in field_content:
                if isinstance(ut, str) and ut.strip():
                    utterances_texts.append(_clean_text(ut))
        # Podríamos añadir un logging.debug si el contenido no es ni string ni lista, o está vacío

    if not utterances_texts:
        return None  # No hay texto útil en este turno

    # Unimos las utterances para formar un bloque de texto coherente para este turno
    turn_text_combined = " ".join(utterances_texts)

    # Nombre descriptivo para el "documento"
    # Usamos un nombre genérico porque el nombre del personaje/hablante no está directamente aquí
    # y sería demasiado granular para el nombre del documento RAG.
    doc_name = f"Turno de Partida {turn_index + 1}"

    # El prefijo ayuda al LLM a entender el tipo de contexto
    return _format_document("Ejemplo de Partida D&D (FIREBALL)", doc_name, [turn_text_combined])


# --- Función principal de carga de datos MODIFICADA ---
def load_all_data(data_folder, load_fireball=None):

    # Verificamos si queremos cargar fireball
    if load_fireball is None:
        env_val = os.getenv("LOAD_FIREBALL", "1").lower()
        load_fireball = env_val not in ("0", "false", "no")

    all_documents = []
    start_time = time.time()
    json_files = glob.glob(os.path.join(data_folder, "**/*.json"), recursive=True)
    json_files = [f for f in json_files if os.path.basename(f).lower() not in ['package.json']]

    if not json_files:
        logging.warning(f"No se encontraron archivos .json locales en la carpeta: {data_folder}")

    logging.info(f"Procesando {len(json_files)} archivos JSON locales desde {data_folder}...")

    for filepath in json_files:
        filename = os.path.basename(filepath)
        logging.info(f"--- Cargando y procesando archivo local: {filename} ---")
        processed_docs_for_file = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if filename.lower() == 'origenes.json':  #
                processed_docs_for_file = _process_origenes_file(data)
            elif filename.lower() == 'spell.json' and "spells" in data:  #
                for spell_item in data.get("spells", []):
                    processed_docs_for_file.extend(_process_spell(spell_item))
            elif filename.lower() == 'reglas_dnd.json' and isinstance(data, list):  #
                for rule_item in data:
                    processed_docs_for_file.extend(_process_rule(rule_item))
            elif "clase" in data and "descripcion_general" in data:
                processed_docs_for_file = _process_class_file(data, filename)  #
            elif filename.lower() == 'especies.json':  #
                processed_docs_for_file = _process_species_file(data)
            elif filename.lower() == 'equipamiento.json':  #
                processed_docs_for_file = _process_equipment_file(data)
            elif filename.lower() == 'creacionpersonajes.json' and "creacion_personaje" in data:  #
                cp_data = data["creacion_personaje"];
                desc_parts_cp = []
                if "pasos" in cp_data: desc_parts_cp.append(f"Pasos creación: {', '.join(cp_data['pasos'])}.")
                if "componentes" in cp_data:
                    for n, d_ in cp_data["componentes"].items(): desc_parts_cp.append(
                        f"Componente '{n.capitalize()}': {d_}.")
                doc = _format_document("Guía Creación Personajes", "General", desc_parts_cp)
                if doc: processed_docs_for_file.append(doc)
            elif filename.lower() == 'introduction.json' and "introduccion" in data:  #
                intro_data = data["introduccion"];
                desc_parts_intro = [_clean_text(intro_data.get("descripcion_general"))]
                if "roles" in intro_data:
                    desc_parts_intro.append(f"Rol Jugador: {_clean_text(intro_data['roles'].get('jugador'))}")
                    desc_parts_intro.append(f"Rol DM: {_clean_text(intro_data['roles'].get('director_de_juego'))}")
                if "componentes_basicos" in intro_data: desc_parts_intro.append(
                    f"Componentes básicos: {', '.join(intro_data.get('componentes_basicos', []))}.")
                doc = _format_document("Introducción D&D", "General", desc_parts_intro)
                if doc: processed_docs_for_file.append(doc)
            else:
                logging.warning(f"Archivo local {filename} sin procesador específico, usando genérico.")
                default_prefix = filename.replace('.json', '').replace('_', ' ').capitalize()
                if isinstance(data, list):
                    for item_dict in data:
                        if isinstance(item_dict, dict):
                            doc = _process_generic_item(item_dict, default_prefix)
                            if doc: processed_docs_for_file.append(doc)
                elif isinstance(data, dict):
                    doc = _process_generic_item(data, default_prefix)
                    if doc: processed_docs_for_file.append(doc)

            valid_docs_local = [doc for doc in processed_docs_for_file if doc]
            if valid_docs_local:
                all_documents.extend(valid_docs_local)
            logging.info(f"Procesados {len(valid_docs_local)} fragmentos válidos de '{filename}'.")
        except json.JSONDecodeError as je:
            logging.error(f"Error JSON en {filename}: {je}", exc_info=False)  # No exc_info para errores comunes de JSON
        except Exception as e:
            logging.error(f"Error procesando {filename}: {e}", exc_info=True)

    # --- CARGA Y PROCESAMIENTO DEL DATASET FIREBALL (OPCIONAL) ---
    if load_fireball:
        logging.info("--- Intentando cargar y procesar el dataset FIREBALL desde Hugging Face ---")
        try:
            # Carga solo los primeros 1000 ejemplos del split 'train' para prueba
            num_fireball_examples = 1000
            fireball_dataset = load_dataset("lara-martin/FIREBALL", split=f'train[:{num_fireball_examples}]')

            fireball_docs_count = 0
            for i, turn_entry in enumerate(fireball_dataset):
                processed_fireball_doc = _process_fireball_turn(turn_entry, i)
                if processed_fireball_doc:
                    all_documents.append(processed_fireball_doc)
                    fireball_docs_count += 1
            logging.info(
                f"Procesados {fireball_docs_count} de {num_fireball_examples} turnos solicitados del dataset FIREBALL.")

        except ImportError:
            logging.error(
                "La librería 'datasets' no está instalada. No se puede cargar FIREBALL. Instala con: pip install datasets")
        except Exception as e:  # Captura errores más específicos de carga de HF si ocurren
            if os.getenv("HF_DATASETS_OFFLINE") == "1":
                logging.warning("Modo offline detectado. Se omite la carga del dataset FIREBALL.")
            else:
                logging.error(f"Error al cargar o procesar el dataset FIREBALL: {e}", exc_info=True)
            logging.warning("Continuando sin los datos de FIREBALL.")
    else:
        logging.info("Carga del dataset FIREBALL deshabilitada.")
    # --- FIN DEL PROCESAMIENTO DE FIREBALL ---

    dataset_msg = "y FIREBALL" if load_fireball else ""
    logging.info(
        f"Carga total de datos (locales {dataset_msg}) completada en {time.time() - start_time:.2f} segundos. Total de documentos RAG: {len(all_documents)}")
    return all_documents


def build_index_from_scratch(documents):  #
    global faiss_index, indexed_docs
    logging.info("Construyendo índice FAISS desde cero...")
    if not documents:
        logging.error("No hay documentos para construir el índice.")
        return None, None
    model = get_embedding_model()
    if not model:
        logging.error("Modelo de embeddings no disponible para construir el índice.")
        return None, None

    logging.info(f"Generando embeddings para {len(documents)} documentos...")
    try:
        embeddings = model.encode(documents, show_progress_bar=True, batch_size=64)
    except Exception as e:
        logging.error(f"Error durante la codificación de embeddings: {e}", exc_info=True)
        return None, None

    embeddings_np = np.array(embeddings).astype('float32')
    if embeddings_np.ndim == 1:
        embeddings_np = np.expand_dims(embeddings_np, axis=0)
    if embeddings_np.shape[0] == 0 or embeddings_np.shape[1] == 0:
        logging.error("No se generaron embeddings válidos.")
        return None, None

    faiss_index = faiss.IndexFlatL2(embeddings_np.shape[1])
    faiss_index.add(embeddings_np)
    logging.info(f"Índice FAISS construido. Vectores: {faiss_index.ntotal}")

    try:
        os.makedirs(os.path.dirname(INDEX_FILE_PATH), exist_ok=True)
        faiss.write_index(faiss_index, INDEX_FILE_PATH)
        with open(DOCUMENTS_FILE_PATH, 'wb') as f:
            pickle.dump(documents, f)
        logging.info(f"Índice FAISS guardado en: {INDEX_FILE_PATH}")
        logging.info(f"Documentos guardados en: {DOCUMENTS_FILE_PATH}")
    except Exception as e:
        logging.error(f"Error guardando índice o documentos: {e}", exc_info=True)
    indexed_docs = documents
    return faiss_index, indexed_docs


def build_or_load_index(docs_for_rebuild=None):  #
    global faiss_index, indexed_docs
    if faiss_index is not None and indexed_docs is not None:
        return faiss_index, indexed_docs
    if os.path.exists(INDEX_FILE_PATH) and os.path.exists(DOCUMENTS_FILE_PATH):
        logging.info(f"Cargando índice FAISS existente desde {INDEX_FILE_PATH}...")
        try:
            faiss_index = faiss.read_index(INDEX_FILE_PATH)
            with open(DOCUMENTS_FILE_PATH, 'rb') as f:
                indexed_docs = pickle.load(f)
            if faiss_index.ntotal != len(indexed_docs):
                logging.warning(
                    f"Discrepancia: Vectores FAISS ({faiss_index.ntotal}) vs Documentos ({len(indexed_docs)}). Reconstruyendo...")
                if docs_for_rebuild is None:
                    logging.error("Se necesita reconstruir pero no se proporcionaron documentos.")
                    return None, None
                return build_index_from_scratch(docs_for_rebuild)
            logging.info(f"Índice FAISS ({faiss_index.ntotal} vectores) y {len(indexed_docs)} docs cargados.")
            return faiss_index, indexed_docs
        except Exception as e:
            logging.error(f"Error cargando índice/docs: {e}. Reconstruyendo...", exc_info=True)
            if docs_for_rebuild is None:
                logging.error("Se necesita reconstruir por error de carga pero no se proporcionaron documentos.")
                return None, None
            return build_index_from_scratch(docs_for_rebuild)
    else:
        logging.info("Índice o documentos no encontrados. Construyendo desde cero...")
        if docs_for_rebuild is None or not docs_for_rebuild:
            logging.warning("Se necesita construir pero no se proporcionaron documentos.")
            return None, None
        return build_index_from_scratch(docs_for_rebuild)


def search_relevant_info(query, k=3):  #
    global faiss_index, indexed_docs
    logging.debug(f"Búsqueda RAG para: '{query}' (top {k})")
    if faiss_index is None or indexed_docs is None:
        faiss_index, indexed_docs = build_or_load_index()  # Asegura que esté cargado/construido
    if not faiss_index or not indexed_docs:
        logging.error("Índice o documentos no disponibles para búsqueda RAG.")
        return []
    model = get_embedding_model()
    if not model:
        logging.error("Modelo de embeddings no disponible para búsqueda RAG.")
        return []
    try:
        query_embedding = model.encode([query])
        query_embedding_np = np.array(query_embedding).astype('float32')
        actual_k = min(k, faiss_index.ntotal)
        if actual_k == 0:
            logging.info("Índice FAISS vacío.")
            return []
        distances, indices = faiss_index.search(query_embedding_np, actual_k)
        results = [indexed_docs[idx] for idx in indices[0] if idx != -1]
        logging.debug(f"Búsqueda RAG completada. Documentos encontrados: {len(results)}")
        return results
    except Exception as e:
        logging.error(f"Error en búsqueda RAG: {e}", exc_info=True)
        return []


if __name__ == '__main__':
    logging.info(f"Ejecutando rag_utils.py directamente para construir/probar el índice. Datos en: {DATA_FOLDER_PATH}")
    all_docs_loaded = load_all_data(DATA_FOLDER_PATH)

    if all_docs_loaded:
        print(f"\nCargados {len(all_docs_loaded)} fragmentos de documentos.")
        index, indexed_documents_list = build_or_load_index(all_docs_loaded)

        if index and indexed_documents_list:
            print(
                f"Índice FAISS listo con {index.ntotal} vectores y {len(indexed_documents_list)} documentos cacheados.")

            queries_de_prueba = [
                "Especie Drow", "Características del Elfo del Bosque", "Rasgos del Aasimar",
                "¿Qué es una tirada de ataque?", "Hechizo Bola de Fuego", "Reglas de la condición Aturdido",
                "Origen Acólito", "Origen Marinero", "Habilidades del Pícaro Asesino",
                "Arma Espada Larga", "¿Cómo funciona la CA?", "Moneda de Oro",
                "Ejemplo de cómo un jugador podría describir el lanzamiento de un hechizo de fuego",  # Para FIREBALL
                "Una conversación típica en una taberna de D&D sobre un tesoro perdido",  # Para FIREBALL
                "Cómo reacciona un personaje a una trampa de flechas en un pasillo"  # Para FIREBALL
            ]

            for q_test in queries_de_prueba:
                print(f"\n--- Buscando para la query: '{q_test}' ---")
                resultados_busqueda = search_relevant_info(q_test, k=2)
                if resultados_busqueda:
                    for idx_res, doc_res in enumerate(resultados_busqueda):
                        print(f"--- Resultado {idx_res + 1} para '{q_test}' ---")
                        print(doc_res[:500] + "..." if len(doc_res) > 500 else doc_res)  # Mostrar snippet
                else:
                    print(f"No se encontraron resultados para '{q_test}'.")
        else:
            print("Error: El índice FAISS o la lista de documentos no se construyeron o cargaron correctamente.")
    else:
        print("Error: No se cargaron documentos desde la carpeta de datos. El índice no se puede construir.")
