"""
Backend de IA de Helion. Soporta dos modos, según la variable AI_BACKEND:

  AI_BACKEND=groq   -> usa la API gratuita de Groq (por internet).
                       Recomendado si alojas el bot en Railway/Render/VPS
                       ligero, porque no necesita recursos extra.

  AI_BACKEND=ollama -> usa Ollama corriendo LOCALMENTE (sin nube, sin
                       APIs de terceros). Necesitas tener Ollama
                       instalado y un modelo descargado en LA MISMA
                       máquina donde corre este bot.
                       ⚠️ Esto requiere bastante RAM (varios GB según
                       el modelo) — no funciona bien en hostings
                       ligeros como el plan gratuito de Railway. Está
                       pensado para tu propio PC o un servidor propio
                       con recursos de sobra.
"""

import asyncio
import os

AI_BACKEND = os.getenv("AI_BACKEND", "groq").lower()

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

_groq_client = None


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        api_key = os.getenv("GROQ_API_KEY")
        _groq_client = Groq(api_key=api_key) if api_key else None
    return _groq_client


async def ask(system_prompt: str, user_prompt: str) -> str:
    if AI_BACKEND == "ollama":
        return await _ask_ollama(system_prompt, user_prompt)
    return await _ask_groq(system_prompt, user_prompt)


async def _ask_groq(system_prompt: str, user_prompt: str) -> str:
    client = _get_groq_client()
    if client is None:
        return "⚠️ Falta configurar GROQ_API_KEY."
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=GROQ_MODEL,
            max_tokens=500,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content.strip() or "No supe qué responder a eso 😅"
    except Exception as e:
        return f"⚠️ Tuve un error hablando con Groq: {e}"


async def _ask_ollama(system_prompt: str, user_prompt: str) -> str:
    try:
        import ollama
    except ImportError:
        return "⚠️ Falta instalar el paquete 'ollama' (pip install ollama)."

    def _run():
        client = ollama.Client(host=OLLAMA_HOST)
        r = client.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return r["message"]["content"]

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        return (
            f"⚠️ Error hablando con Ollama (¿está corriendo `ollama serve` "
            f"y descargado el modelo '{OLLAMA_MODEL}'?): {e}"
        )
