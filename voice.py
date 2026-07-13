"""
Módulo de voz de Helion (EXPERIMENTAL).

Qué hace:
1. Une al bot al canal de voz de quien se lo pida.
2. Mientras está conectado, graba en ciclos cortos (por defecto 5 segundos)
   el audio de cada persona que habla.
3. Cada ciclo, transcribe el audio con Whisper (local, offline) buscando la
   palabra de activación "Hey Helion" (o variantes en español).
4. Si la encuentra, toma lo que se dijo después, se lo pasa a la misma IA
   que usa el chat de texto, y reproduce la respuesta en la llamada usando
   texto a voz (gTTS).

⚠️ Limitaciones a tener en cuenta (léelas antes de confiar en esto):
- La captura de audio se basa en py-cord (discord.py NO soporta recibir
  audio de forma oficial), así que este mecanismo puede romperse con
  actualizaciones de Discord o de la librería.
- Al grabar en ciclos de N segundos, una frase que quede "cortada" entre
  dos ciclos puede no transcribirse bien. No es un reconocimiento de voz
  fluido en tiempo real, es más bien "graba 5s -> procesa -> repite".
- Whisper corriendo en CPU puede tardar unos segundos en transcribir cada
  ciclo, así que la respuesta del bot en la llamada no será instantánea.
- gTTS requiere que el servidor donde corre el bot tenga acceso a
  internet (usa la API pública de Google Translate para generar la voz).
- Necesitas tener `ffmpeg` instalado en el sistema donde corra el bot.
"""

import asyncio
import os
import re
import tempfile

import discord
from gtts import gTTS

try:
    import whisper
except ImportError:
    whisper = None

RECORD_SECONDS = int(os.getenv("VOICE_RECORD_SECONDS", "5"))
WAKE_WORDS = ["hey helion", "ey helion", "oye helion", "hola helion"]

# Modelo de Whisper: "tiny" o "base" son rápidos pero menos precisos;
# "small"/"medium" son más precisos pero más lentos y pesados en RAM/CPU.
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "base")

_whisper_model = None
# Estado por servidor: guild_id -> {"listening": bool, "task": asyncio.Task}
_guild_state: dict[int, dict] = {}


def _get_whisper_model():
    global _whisper_model
    if whisper is None:
        raise RuntimeError(
            "El paquete 'openai-whisper' no está instalado. "
            "Corre: pip install openai-whisper"
        )
    if _whisper_model is None:
        _whisper_model = whisper.load_model(WHISPER_MODEL_NAME)
    return _whisper_model


def _extract_after_wake_word(text: str) -> str | None:
    """
    Si el texto empieza (o contiene cerca del inicio) una wake word,
    devuelve lo que sigue después de ella. Si no, devuelve None.
    """
    lowered = text.lower().strip()
    for wake in WAKE_WORDS:
        idx = lowered.find(wake)
        if idx != -1 and idx < 15:  # debe estar cerca del principio
            remainder = text[idx + len(wake):].strip(" ,.:;-")
            return remainder
    return None


async def join_call(member: discord.Member) -> discord.VoiceClient | None:
    """Conecta al bot al canal de voz donde esté el miembro que lo invocó."""
    if not member.voice or not member.voice.channel:
        return None
    channel = member.voice.channel
    guild = member.guild

    existing = guild.voice_client
    if existing and existing.channel.id == channel.id:
        return existing
    if existing:
        await existing.move_to(channel)
        return existing

    return await channel.connect()


async def leave_call(guild: discord.Guild):
    stop_listening(guild.id)
    if guild.voice_client:
        await guild.voice_client.disconnect(force=True)


def is_listening(guild_id: int) -> bool:
    return _guild_state.get(guild_id, {}).get("listening", False)


def stop_listening(guild_id: int):
    state = _guild_state.get(guild_id)
    if state:
        state["listening"] = False
        task = state.get("task")
        if task and not task.done():
            task.cancel()


async def start_listening(guild: discord.Guild, ask_ai_func):
    """
    Inicia el ciclo de escucha continua (grabar N segundos -> transcribir
    -> responder si detecta la wake word -> repetir).

    ask_ai_func: función async(prompt: str) -> str, la misma que usa el chat
    de texto, para que Helion responda de forma consistente.
    """
    guild_id = guild.id
    vc = guild.voice_client
    if not vc:
        return

    _guild_state[guild_id] = {"listening": True, "task": None}

    async def loop():
        while _guild_state.get(guild_id, {}).get("listening"):
            try:
                await _record_and_process_cycle(guild, vc, ask_ai_func)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[voice] Error en ciclo de escucha: {e}")
                await asyncio.sleep(2)

    task = asyncio.create_task(loop())
    _guild_state[guild_id]["task"] = task


async def _record_and_process_cycle(guild: discord.Guild, vc: discord.VoiceClient, ask_ai_func):
    """
    Graba RECORD_SECONDS de audio de todos los que hablan, y cuando termina
    procesa lo capturado. Usa el sistema de sinks de py-cord.
    """
    done_event = asyncio.Event()
    captured = {}

    def finished_callback(sink: discord.sinks.Sink, *args):
        captured["sink"] = sink
        done_event.set()

    sink = discord.sinks.WaveSink()
    vc.start_recording(sink, finished_callback)
    try:
        await asyncio.sleep(RECORD_SECONDS)
    finally:
        if vc.recording:
            vc.stop_recording()

    try:
        await asyncio.wait_for(done_event.wait(), timeout=5)
    except asyncio.TimeoutError:
        return

    result_sink = captured.get("sink")
    if not result_sink or not result_sink.audio_data:
        return

    for user_id, audio in result_sink.audio_data.items():
        member = guild.get_member(user_id)
        if member is None or member.bot:
            continue

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            audio.file.seek(0)
            tmp.write(audio.file.read())

        try:
            text = await _transcribe(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        if not text:
            continue

        remainder = _extract_after_wake_word(text)
        if remainder is None:
            continue  # no dijeron la wake word, se ignora

        if not remainder:
            remainder = "Hola"

        reply_text = await ask_ai_func(remainder)
        await _speak(vc, reply_text)


async def _transcribe(wav_path: str) -> str:
    def _run():
        model = _get_whisper_model()
        result = model.transcribe(wav_path, language="es", fp16=False)
        return result.get("text", "").strip()

    return await asyncio.to_thread(_run)


TTS_BACKEND = os.getenv("TTS_BACKEND", "gtts").lower()  # "gtts" o "piper"
PIPER_BINARY = os.getenv("PIPER_BINARY", "piper")
PIPER_VOICE_MODEL = os.getenv("PIPER_VOICE_MODEL", "")  # ruta al .onnx del modelo de voz


def _generate_gtts(text: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        path = tmp.name
    gTTS(text=text, lang="es").save(path)
    return path


def _generate_piper(text: str) -> str:
    """
    Genera audio con Piper (TTS 100% local y gratuito). Requiere tener
    el binario 'piper' instalado y un modelo de voz en español (.onnx)
    descargado, con su ruta en PIPER_VOICE_MODEL.
    """
    import subprocess

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = tmp.name

    subprocess.run(
        [PIPER_BINARY, "--model", PIPER_VOICE_MODEL, "--output_file", path],
        input=text.encode("utf-8"),
        check=True,
    )
    return path


async def _speak(vc: discord.VoiceClient, text: str):
    """Convierte texto a voz (gTTS o Piper, según TTS_BACKEND) y lo reproduce."""
    if not text:
        return

    if TTS_BACKEND == "piper" and PIPER_VOICE_MODEL:
        audio_path = await asyncio.to_thread(_generate_piper, text)
    else:
        audio_path = await asyncio.to_thread(_generate_gtts, text)

    while vc.is_playing():
        await asyncio.sleep(0.3)

    source = discord.FFmpegPCMAudio(audio_path)

    def _after_playback(err):
        try:
            os.remove(audio_path)
        except OSError:
            pass

    vc.play(source, after=_after_playback)
