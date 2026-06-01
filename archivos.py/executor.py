from tools import TOOLS

from memory import memoria

from aliases import aliases

from tts import hablar


def ejecutar(intent, valor):

    # =====================================================
    # NORMALIZAR
    # =====================================================

    intent = str(intent).lower().strip()

    valor = str(valor).lower().strip()


    # =====================================================
    # ALIAS
    # =====================================================

    nombre_real = valor


    for clave_alias, real in aliases.items():

        if isinstance(clave_alias, tuple):

            if valor in [

                x.lower().strip()

                for x in clave_alias

            ]:

                nombre_real = real

                break

        else:

            if valor == str(clave_alias).lower().strip():

                nombre_real = real

                break


    # =====================================================
    # MEMORIA
    # =====================================================

    memoria["ultima_accion"] = intent


    if intent in [

        "abrir_app",

        "cerrar_app"

    ]:

        memoria["ultima_app"] = nombre_real


    # =====================================================
    # VALIDAR TOOL
    # =====================================================

    if intent not in TOOLS:

        hablar(
            "No conozco esa acción"
        )

        return False


    # =====================================================
    # EJECUTAR
    # =====================================================

    try:

        resultado = TOOLS[intent](
            nombre_real
        )

    except Exception as e:

        print(
            "Error ejecutando tool:",
            e
        )

        hablar(
            "Hubo un error ejecutando la acción"
        )

        return False


    # =====================================================
    # SOPORTE PARA TUPLAS
    # =====================================================

    if isinstance(resultado, tuple):

        exito, nombre_decir = resultado

    else:

        exito = resultado

        nombre_decir = nombre_real


    # =====================================================
    # RESPUESTAS ERROR
    # =====================================================

    if not exito:

        if intent == "abrir_app":

            hablar(
                f"No encontré {nombre_decir}"
            )

        elif intent == "cerrar_app":

            hablar(
                f"No pude cerrar {nombre_decir}"
            )

        else:

            hablar(
                "No pude realizar esa acción"
            )

        return False


    # =====================================================
    # RESPUESTAS ÉXITO
    # =====================================================

    if intent == "abrir_app":

        hablar(
            f"Abriendo {nombre_decir}"
        )


    elif intent == "cerrar_app":

        hablar(
            f"Cerrando {nombre_decir}"
        )


    elif intent == "buscar_google":

        hablar(
            f"Buscando {nombre_decir}"
        )


    elif intent == "abrir_url":

        hablar(
            "Abriendo enlace"
        )


    return True