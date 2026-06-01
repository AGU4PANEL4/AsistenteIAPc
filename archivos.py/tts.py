import pyttsx3


def hablar(texto):

    print("Asistente:", texto)

    engine = pyttsx3.init()

    engine.say(texto)

    engine.runAndWait()

    engine.stop()