import ollama

from memory import memoria


ACCIONES_VALIDAS = {

    "abrir_app",

    "cerrar_app",

    "buscar_google",

    "abrir_url"

}


def interpretar_con_ia(texto):

    ultima_app = memoria.get(
        "ultima_app",
        ""
    )

    ultima_accion = memoria.get(
        "ultima_accion",
        ""
    )


    prompt = f"""
Contexto actual:

ultima_app:
{ultima_app}

ultima_accion:
{ultima_accion}


Convierte SOLO si reconoces una acción.

Formato:
accion|valor

Una acción por línea.


Acciones permitidas:

- abrir_app
- cerrar_app
- buscar_google
- abrir_url


Ejemplos:

Usuario:
abre discord

Respuesta:
abrir_app|discord


Usuario:
cierra discord

Respuesta:
cerrar_app|discord


Usuario:
busca videos de gatos

Respuesta:
buscar_google|videos de gatos


Usuario:
abre youtube.com

Respuesta:
abrir_url|youtube.com


IMPORTANTE:

- Si el usuario dice "ciérralo"
usa la ultima_app.

- Si el usuario dice "ábrelo"
usa la ultima_app.

- NO inventes acciones.

- SOLO responde con:
accion|valor


Si NO entiendes responde EXACTAMENTE:

ninguna


Usuario:
{texto}
"""


    respuesta = ollama.chat(

        model="gemma3",

        messages=[

            {

                "role": "user",

                "content": prompt

            }

        ]

    )


    salida = (

        respuesta["message"]["content"]

        .strip()

        .lower()

    )


    print(
        "IA cruda:",
        salida
    )


    if (

        not salida

        or

        salida == "ninguna"

    ):

        return []


    acciones = []


    for linea in salida.splitlines():

        linea = linea.strip()

        if not linea:
            continue

        if "|" not in linea:
            continue

        try:

            intent, valor = linea.split(
                "|",
                1
            )

            intent = intent.strip()

            valor = valor.strip()


            if (

                intent

                not in

                ACCIONES_VALIDAS

            ):

                continue


            if not valor:
                continue


            acciones.append(

                (

                    intent,

                    valor

                )

            )

        except Exception as e:

            print(
                "Error parseando IA:",
                e
            )


    return acciones