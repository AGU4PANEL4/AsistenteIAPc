import asyncio
import edge_tts

async def test():
    communicate = edge_tts.Communicate("Hola, soy tu asistente", voice="es-CO-SalomeNeural")
    await communicate.save("test.mp3")

asyncio.run(test())