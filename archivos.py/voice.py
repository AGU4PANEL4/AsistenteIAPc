import speech_recognition as sr

# =========================================================
# RECOGNIZER - configurar una sola vez
# =========================================================

recognizer = sr.Recognizer()
recognizer.energy_threshold         = 300
recognizer.dynamic_energy_threshold = True
# FIX: 1.2s a veces cortaba la frase si el usuario hacía una pausa
# corta a mitad de la oración (pensando qué decir). Subirlo da un
# poco más de margen antes de considerar que terminó de hablar.
recognizer.pause_threshold          = 1.5
recognizer.phrase_threshold         = 0.3
recognizer.non_speaking_duration    = 0.8


def _calibrar(duracion=2):
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=duracion)


print("[Micrófono] Calibrando...")
_calibrar(duracion=2)
print("[Micrófono] Listo")


def recalibrar():
    """
    Vuelve a medir el ruido de fondo. La calibración inicial se
    hace una sola vez al arrancar, pero si el volumen del juego,
    de la música, o el ruido del cuarto cambia durante el uso, el
    umbral de energía se queda desactualizado y empieza a cortar
    palabras o a no detectar que estás hablando. Llamar esto de
    vez en cuando (por ejemplo, cada vez que se activa una nueva
    sesión con la wake word) ayuda a mantenerlo al día sin tener
    que recalibrar antes de cada comando, lo cual sí se notaría
    como demora.
    """
    try:
        _calibrar(duracion=0.6)
    except Exception as e:
        print("[Micrófono] No pude recalibrar:", e)

# =========================================================
# ESCUCHAR NORMAL
# =========================================================

def escuchar():

    with sr.Microphone() as source:
        print("Escuchando...")
        try:
            audio = recognizer.listen(
                source,
                timeout=5,
                # FIX: 8s cortaba comandos un poco más largos
                # ("registra alias para tal app y tal otro alias").
                phrase_time_limit=12
            )
        except sr.WaitTimeoutError:
            return ""

    try:
        return recognizer.recognize_google(
            audio,
            language="es-CO"
        ).lower()
    except sr.UnknownValueError:
        return ""
    except sr.RequestError:
        return ""

# =========================================================
# ESCUCHAR CON TIMEOUT CORTO
# Para el hilo de cancelación — escucha rápido y no bloquea
# =========================================================

def escuchar_rapido(timeout=2, phrase_time_limit=3):

    with sr.Microphone() as source:
        try:
            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_time_limit
            )
        except sr.WaitTimeoutError:
            return ""

    try:
        return recognizer.recognize_google(
            audio,
            language="es-CO"
        ).lower()
    except:
        return ""