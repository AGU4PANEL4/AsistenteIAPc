import re

from aliases import aliases


def normalizar(comando):

    comando = comando.lower().strip()


    if comando.startswith("sierra"):

        comando = comando.replace(
            "sierra",
            "cierra",
            1
        )


    return comando



def traducir_alias(nombre):

    nombre = nombre.lower().strip()


    for claves, real in aliases.items():

        if isinstance(claves, tuple):

            for alias in claves:

                if alias.lower() == nombre:

                    return real

        else:

            if claves.lower() == nombre:

                return real


    return nombre


def detectar_intent(comando):

    comando = normalizar(comando)


    # =====================================================
    # BUSCAR GOOGLE
    # =====================================================

    if comando.startswith(

        ("busca ", "buscar ")

    ):

        busqueda = (

            comando

            .replace("buscar", "", 1)

            .replace("busca", "", 1)

            .strip()

        )

        if busqueda:

            return (

                "buscar_google",

                busqueda

            )


    # =====================================================
    # URL
    # =====================================================

    if (

        "http://" in comando

        or

        "https://" in comando

        or

        "www." in comando

    ):

        return (

            "abrir_url",

            comando

        )


    # =====================================================
    # ABRIR APP
    # =====================================================

    abrir = [

        "abre ",

        "abrir ",

        "inicia ",

        "ejecuta "

    ]


    for palabra in abrir:

        if comando.startswith(palabra):

            nombre = (

                comando

                .replace(
                    palabra,
                    "",
                    1
                )

                .strip()

            )

            nombre = traducir_alias(
                nombre
            )


            if nombre:

                return (

                    "abrir_app",

                    nombre

                )


    # =====================================================
    # CERRAR APP
    # =====================================================

    cerrar = [

        "cierra ",

        "cerrar ",

        "termina ",

        "apaga "

    ]


    for palabra in cerrar:

        if comando.startswith(palabra):

            nombre = (

                comando

                .replace(
                    palabra,
                    "",
                    1
                )

                .strip()

            )

            nombre = traducir_alias(
                nombre
            )


            if nombre:

                return (

                    "cerrar_app",

                    nombre

                )


    # ==========================================
    # REFERENCIAS A ÚLTIMA APP
    # ==========================================

    from memory import memoria

    ultima = memoria.get("ultima_app")

    if ultima:

        if comando in [

            "cierralo",

            "ciérralo",

            "cerralo",

            "cierralo",

            "sierra"

        ]:

            return "cerrar_app", ultima


        if comando in [

            "abrelo",

            "ábrelo"

        ]:

            return "abrir_app", ultima

    return None, None