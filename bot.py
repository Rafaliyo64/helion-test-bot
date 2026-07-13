"""
Helion - Bot de Discord con chat de IA y moderación semi-automática.

Funcionalidad:
1. Si mencionan al bot y le hablan normal -> responde usando IA (Claude).
2. Si mencionan al bot y le piden "revisar el server" / "revisar servidor"
   -> SOLO si quien lo pide tiene permiso de moderación (kick/ban o el rol
   configurado en MOD_ROLE_NAME), escanea los mensajes recientes buscando
   actividad sospechosa, borra los mensajes problemáticos, y:
     - Manda un resumen al canal donde se pidió (si hubo o no amenazas).
     - Manda un DM a cada uno de los administradores configurados en
       MOD_USER_IDS explicando el caso, con 3 botones: Aviso / Expulsar /
       Banear. La acción final la decide el admin que pulse un botón.
3. En el canal configurado en LISTEN_CHANNEL_ID, el bot responde
   automáticamente a TODO mensaje sin necesidad de mencionarlo.
4. Si le dices "@Helion únete a la llamada" (estando tú en un canal de
   voz), se conecta y empieza a escuchar. Si dices "Hey Helion, <algo>"
   en la llamada, te responde por voz usando IA (EXPERIMENTAL - ver
   voice.py para detalles y limitaciones). "@Helion sal de la llamada"
   para que se desconecte.
5. Música: "@Helion reproduce musica" reproduce algo aleatorio,
   "@Helion reproduce <link o nombre de canción>" reproduce eso
   específico. En ambos casos el bot manda un mensaje con botones para
   retroceder 10s, adelantar 10s, o saltar a otra canción (ver
   music.py).

Antes de correrlo:
  pip install -r requirements.txt
  cp .env.example .env   (y rellena tus valores)
  python bot.py
"""

import os
import re
import asyncio

import discord
from discord.ext import commands
from dotenv import load_dotenv

import moderation
import voice
import music
import ai_backend
import memoria
import piezas
import forja
import youtube_announcer

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LISTEN_CHANNEL_ID = int(os.getenv("LISTEN_CHANNEL_ID", "0"))
MOD_ROLE_NAME = os.getenv("MOD_ROLE_NAME", "").strip()
PERSONALITY_FILE = os.getenv("PERSONALITY_FILE", "helion_personalidad.txt")

# IDs de los administradores que reciben el DM con los botones de decisión
MOD_USER_IDS = [
    int(uid.strip())
    for uid in os.getenv("MOD_USER_IDS", "1505978108128530604,1525991928439636099").split(",")
    if uid.strip()
]

# Cuántos mensajes recientes revisa por canal al hacer un "escaneo del server"
SCAN_MESSAGES_PER_CHANNEL = 100

MODERATION_TRIGGERS = [
    "revisa el server", "revisar el server", "revisa el servidor",
    "revisar el servidor", "revisa la server", "chequea el server",
    "chequea el servidor", "escanea el server", "escanea el servidor",
]

JOIN_CALL_TRIGGERS = [
    "únete a mi llamada", "unete a mi llamada", "únete a la llamada",
    "unete a la llamada", "entra a la llamada", "entra a mi llamada",
    "conéctate a la llamada", "conectate a la llamada", "ven a la llamada",
]

LEAVE_CALL_TRIGGERS = [
    "sal de la llamada", "sal de mi llamada", "desconéctate",
    "desconectate", "vete de la llamada", "abandona la llamada",
]

MUSIC_TRIGGERS = [
    "reproduce", "pon musica", "pon música", "toca musica", "toca música",
]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def load_personality() -> str:
    """
    Lee helion_personalidad.txt (editable sin tocar código) y le añade el
    estado real del robot, si existe estado_helion.json, para que Helion
    hable de su construcción real sin inventar nada.
    """
    if os.path.exists(PERSONALITY_FILE):
        with open(PERSONALITY_FILE, encoding="utf-8") as f:
            base = f.read().strip()
    else:
        base = (
            "Eres Helion, el asistente de IA de este servidor de Discord. "
            "Responde de forma amigable, cercana y breve, en español."
        )

    estado_texto = forja.read_estado_text()
    if estado_texto:
        base += "\n\nEstado actual real de tu construcción (no inventes nada más allá de esto):\n" + estado_texto

    return base


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def strip_mention(content: str, bot_user_id: int) -> str:
    """Quita la mención al bot del inicio/cualquier parte del mensaje."""
    return re.sub(rf"<@!?{bot_user_id}>", "", content).strip()


def user_can_moderate(member: discord.Member) -> bool:
    if member.guild_permissions.kick_members or member.guild_permissions.ban_members:
        return True
    if MOD_ROLE_NAME:
        return any(role.name == MOD_ROLE_NAME for role in member.roles)
    return False


async def ask_ai(prompt: str, user_id=None) -> str:
    system_prompt = load_personality()

    if user_id is not None:
        recuerdos = memoria.recordar(user_id)
        if recuerdos:
            system_prompt += "\n\nEsto sabes de esta persona (de charlas anteriores):\n"
            system_prompt += "\n".join(f"- {r}" for r in recuerdos)

    reply = await ai_backend.ask(system_prompt, prompt)

    if user_id is not None and reply and not reply.startswith("⚠️"):
        resumen_prompt = f"Pregunta: {prompt}\nRespuesta: {reply}"
        resumen = await ai_backend.ask(
            "Resume en una sola frase corta y neutra de qué trató este "
            "intercambio. Responde solo con la frase, nada más.",
            resumen_prompt,
        )
        if resumen and not resumen.startswith("⚠️"):
            memoria.guardar(user_id, resumen.strip()[:200])

    return reply


# ---------------------------------------------------------------------------
# Vista con los botones de decisión (Aviso / Expulsar / Banear)
# ---------------------------------------------------------------------------

class ModerationDecisionView(discord.ui.View):
    """
    Se envía por DM a cada administrador en MOD_USER_IDS. El primero que
    pulse un botón decide la acción; se marca como resuelto en ambos DMs
    para evitar acciones duplicadas.
    """

    def __init__(self, guild_id: int, guild_name: str, author_id: int,
                 author_name: str, reason: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.guild_name = guild_name
        self.author_id = author_id
        self.author_name = author_name
        self.reason = reason
        self.resolved = False
        self.sibling_messages: list[discord.Message] = []

    async def _finalize(self, interaction: discord.Interaction,
                         action_label: str, action):
        if interaction.user.id not in MOD_USER_IDS:
            await interaction.response.send_message(
                "🔒 No tienes permiso para resolver esto.", ephemeral=True
            )
            return
        if self.resolved:
            await interaction.response.send_message(
                "Ya se resolvió este caso.", ephemeral=True
            )
            return
        self.resolved = True

        try:
            await action()
            result_text = f"\n\n✅ **Acción aplicada: {action_label}** (por {interaction.user})."
        except discord.Forbidden:
            result_text = f"\n\n⚠️ No tengo permisos suficientes para aplicar: {action_label}."
        except discord.HTTPException as e:
            result_text = f"\n\n⚠️ No se pudo aplicar la acción: {e}"

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=interaction.message.content + result_text, view=self
        )
        for msg in self.sibling_messages:
            if msg.id != interaction.message.id:
                try:
                    await msg.edit(content=msg.content + result_text, view=self)
                except discord.HTTPException:
                    pass

    def _get_member(self) -> discord.Member | None:
        guild = bot.get_guild(self.guild_id)
        return guild.get_member(self.author_id) if guild else None

    @discord.ui.button(label="Aviso", style=discord.ButtonStyle.secondary, emoji="⚠️")
    async def warn_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = self._get_member()

        async def action():
            if member:
                await member.send(
                    f"⚠️ Aviso de **{self.guild_name}**: un moderador revisó un "
                    f"mensaje tuyo relacionado con: {self.reason}. Este es un "
                    f"aviso oficial, evita que se repita."
                )
        await self._finalize(interaction, "Aviso", action)

    @discord.ui.button(label="Expulsar", style=discord.ButtonStyle.primary, emoji="👢")
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = self._get_member()

        async def action():
            if member:
                guild = bot.get_guild(self.guild_id)
                try:
                    await member.send(
                        f"🚫 Has sido expulsado de **{self.guild_name}** por: {self.reason}"
                    )
                except discord.Forbidden:
                    pass
                await guild.kick(member, reason=f"Helion - decisión de moderador: {self.reason}")
        await self._finalize(interaction, "Expulsión", action)

    @discord.ui.button(label="Banear", style=discord.ButtonStyle.danger, emoji="⛔")
    async def ban_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = self._get_member()

        async def action():
            if member:
                guild = bot.get_guild(self.guild_id)
                try:
                    await member.send(
                        f"⛔ Has sido baneado permanentemente de **{self.guild_name}** "
                        f"por: {self.reason}"
                    )
                except discord.Forbidden:
                    pass
                await guild.ban(member, reason=f"Helion - decisión de moderador: {self.reason}")
        await self._finalize(interaction, "Baneo permanente", action)


# ---------------------------------------------------------------------------
# Escaneo del servidor
# ---------------------------------------------------------------------------

async def notify_admins(guild: discord.Guild, author: discord.Member, reason: str,
                         channel_name: str, content_snippet: str):
    view = ModerationDecisionView(guild.id, guild.name, author.id, str(author), reason)
    text = (
        f"🔍 **Posible amenaza detectada en {guild.name}**\n"
        f"Usuario: **{author}** ({author.id})\n"
        f"Canal: #{channel_name}\n"
        f"Motivo: {reason}\n"
        f"Fragmento del mensaje: \"{content_snippet[:200]}\"\n\n"
        f"El mensaje ya fue eliminado. ¿Qué acción quieres tomar?"
    )
    for mod_id in MOD_USER_IDS:
        try:
            mod_user = await bot.fetch_user(mod_id)
            msg = await mod_user.send(text, view=view)
            view.sibling_messages.append(msg)
        except discord.HTTPException:
            continue


async def run_server_scan(guild: discord.Guild, requested_by: discord.Member) -> str:
    """
    Escanea los canales de texto del servidor buscando mensajes sospechosos.
    Borra el mensaje encontrado y notifica a los administradores para que
    decidan la sanción (no hay sanción automática).
    """
    deleted = 0
    incidents = 0

    for channel in guild.text_channels:
        perms = channel.permissions_for(guild.me)
        if not (perms.read_message_history and perms.manage_messages):
            continue

        try:
            async for message in channel.history(limit=SCAN_MESSAGES_PER_CHANNEL):
                if message.author.bot:
                    continue

                reason = moderation.is_suspicious(message.content, len(message.mentions))
                if not reason:
                    continue

                author = message.author
                content_snippet = message.content

                try:
                    await message.delete()
                    deleted += 1
                except discord.HTTPException:
                    pass

                if isinstance(author, discord.Member):
                    await notify_admins(guild, author, reason, channel.name, content_snippet)
                    incidents += 1

        except discord.Forbidden:
            continue

    if incidents == 0:
        return (
            f"✅ Escaneo completado (pedido por {requested_by.mention}): "
            f"no se encontró actividad sospechosa."
        )
    return (
        f"🔍 Escaneo completado (pedido por {requested_by.mention}): "
        f"se encontraron **{incidents}** posible(s) amenaza(s), se eliminaron "
        f"{deleted} mensaje(s). Los administradores fueron notificados por DM "
        f"para decidir la sanción."
    )


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    print(f"✅ Conectado como {bot.user} (ID: {bot.user.id})")
    bot.loop.create_task(youtube_announcer.start_loop(bot))


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Sistema de piezas: cualquier mensaje con sustancia en el server suma
    if message.guild is not None:
        piezas.registrar_mensaje(message.author.id, message.content)

    is_mentioned = bot.user in message.mentions
    is_listen_channel = message.channel.id == LISTEN_CHANNEL_ID

    if not is_mentioned and not is_listen_channel:
        await bot.process_commands(message)
        return

    content = strip_mention(message.content, bot.user.id) if is_mentioned else message.content

    if is_mentioned and content.lower().startswith(tuple(MUSIC_TRIGGERS)):
        remainder = content
        for trig in MUSIC_TRIGGERS:
            if content.lower().startswith(trig):
                remainder = content[len(trig):].strip()
                break

        if not isinstance(message.author, discord.Member) or not message.author.voice:
            await message.reply(
                "❌ Necesitas estar en un canal de voz para pedirme música.",
                mention_author=False,
            )
            return

        await message.reply("🎵 Buscando música, dame un segundo...", mention_author=False)
        async with message.channel.typing():
            title, view = await music.start_playback(
                message.author, remainder if remainder else None
            )
        if title is None:
            await message.channel.send("❌ No pude reproducir eso, intenta con otra cosa.")
            return
        await message.channel.send(f"▶️ Reproduciendo: **{title}**", view=view)
        return

    if is_mentioned and any(trigger in content.lower() for trigger in JOIN_CALL_TRIGGERS):
        vc = await voice.join_call(message.author)
        if vc is None:
            await message.reply(
                "❌ Necesitas estar conectado a un canal de voz para que me una.",
                mention_author=False,
            )
            return
        await message.reply(
            f"🔊 Me uní a **{vc.channel.name}**. Di \"Hey Helion\" seguido de lo "
            f"que quieras preguntarme y te responderé por voz.\n"
            f"⚠️ Esta función es experimental: puede tardar unos segundos en "
            f"responder y a veces no entender bien frases cortadas.",
            mention_author=False,
        )
        await voice.start_listening(message.guild, ask_ai)
        return

    if is_mentioned and any(trigger in content.lower() for trigger in LEAVE_CALL_TRIGGERS):
        if message.guild.voice_client:
            await voice.leave_call(message.guild)
            await message.reply("👋 Salí de la llamada.", mention_author=False)
        else:
            await message.reply("No estoy en ninguna llamada ahora mismo.", mention_author=False)
        return

    if is_mentioned and any(trigger in content.lower() for trigger in MODERATION_TRIGGERS):
        if not isinstance(message.author, discord.Member) or not user_can_moderate(message.author):
            await message.reply(
                "🔒 Solo un moderador puede pedirme que revise el servidor.",
                mention_author=False,
            )
            return

        await message.reply(
            "🔍 Entendido, escaneando el servidor... esto puede tardar un momento.",
            mention_author=False,
        )
        async with message.channel.typing():
            summary = await run_server_scan(message.guild, message.author)
        await message.channel.send(summary)
        return

    if not content:
        content = "Hola"

    async with message.channel.typing():
        reply = await ask_ai(content, user_id=message.author.id)
    await message.reply(reply, mention_author=False)

    await bot.process_commands(message)


# ---------------------------------------------------------------------------
# Slash commands: /forja, /nucleo, /ranking, /olvidame
# ---------------------------------------------------------------------------

@bot.slash_command(name="forja", description="Estado real de HELION, el robot")
async def forja_cmd(ctx: discord.ApplicationContext):
    embed = forja.build_embed()
    await ctx.respond(embed=embed)


@bot.slash_command(name="nucleo", description="Tu progreso de piezas en la comunidad")
async def nucleo_cmd(ctx: discord.ApplicationContext):
    fase, total, siguiente = piezas.fase_actual(ctx.author.id)
    await ctx.respond(
        f"🔩 Vas por la fase **{fase}** con **{total}** piezas "
        f"(siguiente fase a las {siguiente})."
    )


@bot.slash_command(name="ranking", description="Los constructores más activos de la comunidad")
async def ranking_cmd(ctx: discord.ApplicationContext):
    top = piezas.ranking(10)
    if not top:
        await ctx.respond("Todavía no hay piezas registradas.")
        return

    lines = []
    for i, (user_id, count) in enumerate(top, start=1):
        member = ctx.guild.get_member(int(user_id)) if ctx.guild else None
        name = member.display_name if member else f"Usuario {user_id}"
        lines.append(f"{i}. {name} — {count} piezas")

    await ctx.respond("🏆 **Ranking de constructores:**\n" + "\n".join(lines))


@bot.slash_command(name="olvidame", description="Borra todo lo que Helion recuerda de ti")
async def olvidame_cmd(ctx: discord.ApplicationContext):
    memoria.olvidar(ctx.author.id)
    await ctx.respond("🧹 Listo, borré todo lo que recordaba de ti.", ephemeral=True)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("Falta DISCORD_TOKEN en el archivo .env")
    bot.run(DISCORD_TOKEN)
