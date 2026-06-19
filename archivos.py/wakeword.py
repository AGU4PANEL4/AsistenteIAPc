from difflib import SequenceMatcher


# =========================================================
# SIMILITUD
# =========================================================

def parecido(a, b):
    return SequenceMatcher(None, a, b).ratio()


# =========================================================
# DETECTAR WAKEWORD
# =========================================================

def detectar_wakeword(texto, wakeword):

    texto    = texto.lower().strip()
    wakeword = wakeword.lower().strip()

    # coincidencia exacta
    if wakeword in texto:
        return True

    palabras_wake = wakeword.split()

    # =====================================================
    # COMPARAR PALABRA POR PALABRA
    # para wakewords de una sola palabra (ej: "jarvis")
    # =====================================================

    if len(palabras_wake) == 1:

        for palabra in texto.split():
            if parecido(palabra, wakeword) > 0.80:
                return True

    # =====================================================
    # COMPARAR VENTANA DE PALABRAS
    # para wakewords de varias palabras (ej: "oye jarvis")
    # =====================================================

    else:

        palabras_texto = texto.split()
        n              = len(palabras_wake)

        for i in range(len(palabras_texto) - n + 1):
            fragmento = " ".join(palabras_texto[i:i + n])
            if parecido(fragmento, wakeword) > 0.80:
                return True

    # =====================================================
    # COMPARAR CONTRA TEXTO COMPLETO
    # por si el usuario solo dijo el wakeword
    # =====================================================

    if parecido(texto, wakeword) > 0.80:
        return True

    return False