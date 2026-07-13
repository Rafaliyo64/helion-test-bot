"""
Módulo de música de Helion.

Uso:
  @Helion reproduce musica          -> reproduce algo aleatorio
  @Helion reproduce <link o nombre> -> reproduce ese link de YouTube (u otra
                                        fuente soportada por yt-dlp), o busca
                                        ese nombre/canción si no es un link

Tras reproducir, el bot manda un mensaje con 3 botones:
  ⏪ -10s   |   +10s ⏩   |   ⏭️ Skip

Requiere:
  - ffmpeg instalado en el sistema (ya lo necesita el módulo de voz)
  - pip install yt-dlp
"""

import asyncio
import random
import time

import discord
import yt_dlp

import voice  # reutilizamos join_call para conectarnos al canal del usuario

YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "source_address": "0.0.0.0",
}

FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

# Términos usados para elegir "algo random" cuando no piden nada específico
RANDOM_SEARCH_TERMS = [
    "top hits 2026", "reggaeton mix", "rock clasico", "pop en español",
    "lofi beats para relajarse", "musica electronica mix", "salsa clasica",
    "banda sonora epica orquestal", "musica para gaming", "indie pop mix",
]

EMPTY_QUERY_WORDS = {
    "", "musica", "música", "una musica", "una música", "algo",
    "cualquiera", "una cancion", "una canción", "random",
}

# Estado por servidor: guild_id -> GuildMusicPlayer
_players: dict[int, "GuildMusicPlayer"] = {}


class GuildMusicPlayer:
    def __init__(self, guild: discord.Guild):
        self.guild = guild
        self.current_stream_url: str | None = None
        self.current_title: str = ""
        self.current_webpage_url: str | None = None
        self.position = 0.0        # segundos ya reproducidos antes del segmento actual
        self._started_at: float | None = None  # time.monotonic() al iniciar el segmento actual

    @property
    def voice_client(self) -> discord.VoiceClient | None:
        return self.guild.voice_client

    def elapsed(self) -> float:
        if self._started_at is None:
            return self.position
        return self.position + (time.monotonic() - self._started_at)

    def mark_started(self, offset: float):
        self.position = max(offset, 0)
        self._started_at = time.monotonic()

    def mark_stopped(self):
        if self._started_at is not None:
            self.position = self.elapsed()
            self._started_at = None


def get_player(guild: discord.Guild) -> GuildMusicPlayer:
    if guild.id not in _players:
        _players[guild.id] = GuildMusicPlayer(guild)
    return _players[guild.id]


def _is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def _build_query(raw_query: str | None) -> str:
    if raw_query is None or raw_query.strip().lower() in EMPTY_QUERY_WORDS:
        return "ytsearch1:" + random.choice(RANDOM_SEARCH_TERMS)
    if _is_url(raw_query):
        return raw_query
    return "ytsearch1:" + raw_query


async def _extract_info(query: str) -> dict:
    def _run():
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(query, download=False)
            if "entries" in info and info["entries"]:
                info = info["entries"][0]
            return info

    return await asyncio.to_thread(_run)


def _start_ffmpeg(player: GuildMusicPlayer, offset: float = 0.0):
    vc = player.voice_client
    if vc is None:
        return
    if vc.is_playing() or vc.is_paused():
        vc.stop()

    before_options = f"{FFMPEG_BEFORE_OPTIONS} -ss {max(offset, 0):.1f}"
    source = discord.FFmpegPCMAudio(
        player.current_stream_url, before_options=before_options, options="-vn"
    )

    def _after(err):
        if err:
            print(f"[music] Error durante la reproducción: {err}")

    vc.play(source, after=_after)
    player.mark_started(offset)


async def play_query(guild: discord.Guild, raw_query: str | None) -> str | None:
    """
    Busca/extrae el audio y lo reproduce desde el principio.
    Devuelve el título de lo que se está reproduciendo, o None si falló.
    """
    player = get_player(guild)
    if player.voice_client is None:
        return None

    query = _build_query(raw_query)
    try:
        info = await _extract_info(query)
    except Exception as e:
        print(f"[music] Error extrayendo info: {e}")
        return None

    stream_url = info.get("url")
    if not stream_url:
        return None

    player.current_stream_url = stream_url
    player.current_title = info.get("title", "Desconocido")
    player.current_webpage_url = info.get("webpage_url")

    _start_ffmpeg(player, offset=0.0)
    return player.current_title


async def start_playback(member: discord.Member, raw_query: str | None) -> tuple[str | None, "MusicControlView | None"]:
    """
    Conecta al bot al canal de voz del usuario (si no está ya) y arranca
    la reproducción. Devuelve (titulo, view) o (None, None) si falló.
    """
    vc = await voice.join_call(member)
    if vc is None:
        return None, None

    title = await play_query(member.guild, raw_query)
    if title is None:
        return None, None

    return title, MusicControlView(member.guild)


def now_playing_text(guild: discord.Guild) -> str:
    player = get_player(guild)
    return f"🎶 Reproduciendo: **{player.current_title}**\nUsa los botones para controlar la música."


class MusicControlView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=None)
        self.guild = guild

    @discord.ui.button(label="⏪ -10s", style=discord.ButtonStyle.secondary)
    async def rewind(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = get_player(self.guild)
        if not player.voice_client or not player.current_stream_url:
            await interaction.response.send_message("No hay nada reproduciéndose.", ephemeral=True)
            return
        new_offset = max(player.elapsed() - 10, 0)
        _start_ffmpeg(player, offset=new_offset)
        await interaction.response.edit_message(content=now_playing_text(self.guild), view=self)

    @discord.ui.button(label="+10s ⏩", style=discord.ButtonStyle.secondary)
    async def forward(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = get_player(self.guild)
        if not player.voice_client or not player.current_stream_url:
            await interaction.response.send_message("No hay nada reproduciéndose.", ephemeral=True)
            return
        new_offset = player.elapsed() + 10
        _start_ffmpeg(player, offset=new_offset)
        await interaction.response.edit_message(content=now_playing_text(self.guild), view=self)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = get_player(self.guild)
        if not player.voice_client:
            await interaction.response.send_message("No estoy en ninguna llamada.", ephemeral=True)
            return
        await interaction.response.defer()
        title = await play_query(self.guild, None)  # salta a algo aleatorio nuevo
        if title is None:
            await interaction.followup.send("⚠️ No pude cargar la siguiente canción.", ephemeral=True)
            return
        await interaction.message.edit(content=now_playing_text(self.guild), view=self)
