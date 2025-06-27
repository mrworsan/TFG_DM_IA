import logging


def resumir_respuesta(bot, respuesta, max_new_tokens=60):
    """Genera un resumen breve utilizando el mismo LLM que el bot.

    Parameters
    ----------
    bot : DungeonMasterBot
        Instancia del bot con el método ``generate_llm_response_sync``.
    respuesta : str
        Texto completo de la respuesta a resumir.
    max_new_tokens : int, optional
        Límite de tokens para el resumen.

    Returns
    -------
    str
        Resumen generado o un fragmento truncado si ocurre un error.
    """
    if not respuesta:
        return ""
    prompt = [
        {"role": "system", "content": "Resume brevemente la siguiente respuesta en una frase:"},
        {"role": "user", "content": respuesta},
    ]
    try:
        resumen = bot.generate_llm_response_sync(
            prompt, max_new_tokens=max_new_tokens, temperature=0.3
        )
        return resumen.strip()
    except Exception as e:
        logging.error(f"Error al resumir respuesta: {e}", exc_info=True)
        return respuesta[:150].strip()
