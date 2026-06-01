import speech_recognition as sr


def escuchar():

    recognizer = sr.Recognizer()


    with sr.Microphone() as source:

        recognizer.adjust_for_ambient_noise(
            source,
            duration=0.3
        )

        print("Escuchando...")


        try:

            audio = recognizer.listen(
                source,
                timeout=3,
                phrase_time_limit=5
            )

        except:

            return ""


    try:

        texto = recognizer.recognize_google(
            audio,
            language="es-ES"
        )

        return texto.lower()


    except:

        return ""