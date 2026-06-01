from difflib import SequenceMatcher


def parecido(a, b):

    return SequenceMatcher(

        None,

        a,

        b

    ).ratio()



def detectar_wakeword(

    texto,

    wakeword

):

    texto = texto.lower()


    palabras = texto.split()


    for palabra in palabras:

        score = parecido(

            palabra,

            wakeword

        )


        if score > 0.75:

            return True


    return False