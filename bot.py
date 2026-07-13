"""
Helion - Bot de Discord con chat de IA, música, voz y moderación asistida.

Funcionalidad:
1. Si mencionan al bot y le hablan normal -> responde usando IA.
2. Si mencionan al bot (o usan /coding) para activar el "modo código" para
   esa persona -> a partir de ahí, Helion le responde como asistente de
   programación en vez de con su personalidad normal (hasta que lo
   desactive otra vez).
3. Moderación: si mencionan al bot pidiéndole revisar el servidor/la
   actividad (o dicen que hay una amenaza), Helion escanea mensajes
   recientes buscando actividad sospechosa (spam, enlaces de phishing,
   malas palabras, etc.), borra lo que encuentra, responde en el canal
   agradeciendo el reporte, y manda un DM a los administradores
   configurados en MOD_USER_IDS con los detalles y 3 botones: Aviso /
   Expulsar / Banear. Al pulsar uno, se abre un formulario donde el
   admin puede escribir un mensaje para el usuario antes de confirmar.
   El usuario afectado recibe un DM con la decisión, el mensaje del
   moderador, y quién la tomó.
4. En el canal configurado en LISTEN_CHANNEL_ID, el bot responde
   automáticamente a TODO mensaje sin necesidad de mencionarlo.
5. Voz: "@Helion únete a la llamada" / "/join" conecta al bot a tu canal
   de voz. "Hey Helion, ..." dentro de la llamada responde por voz
   (EXPERIMENTAL, ver voice.py). "@Helion sal de la llamada" para
   desconectarse.
6. Música: "@Helion reproduce musica" / "/play" reproduce algo aleatorio.
   "@Helion reproduce <link>" / "/play <link o nombre>" reproduce eso
   específico. Manda botones para retroceder 10s, adelantar 10s, o saltar
   a otra canción (ver music.py).

Antes de correrlo:
  pip install -r requirements.txt
  cp .env.example .env   (y rellena tus valores)
  python bot.py
"""

import os
import re

import discord
from discord.ext import commands
from dotenv import load_dotenv

import moderation
import voice
import music
import ai_backend
import youtube_announcer
import tiktok

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

# Palabras clave para detectar el pedido de moderación (combinación flexible,
# no depende de una frase exacta)
MODERATION_VERBS = ["revisa", "revisar", "chequea", "chequear", "escanea", "escanear"]
MODERATION_NOUNS = ["server", "servidor", "actividad", "amenaza", "amenazas"]

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

CODING_ON_TRIGGERS = ["modo codigo", "modo código", "activa el modo codigo", "activa el modo código"]
CODING_OFF_TRIGGERS = ["desactiva el modo codigo", "desactiva el modo código", "sal del modo codigo", "sal del modo código"]

CODING_SYSTEM_PROMPT = (
    "Eres un asistente de programación experto. Responde de forma técnica, "
    "clara y directa, con ejemplos de código cuando ayuden. Sin rodeos "
    "innecesarios ni personalidad extra, solo ayuda técnica precisa."
)

DEFAULT_ACTION_MESSAGES = {
    "Aviso": "Se te ha dado un aviso oficial por tu comportamiento en el servidor.",
    "Expulsión": "Has sido expulsado del servidor por tu comportamiento.",
    "Baneo permanente": "Has sido baneado permanentemente del servidor por tu comportamiento.",
}

# Usuarios con el "modo código" activado (en memoria, se resetea si el bot reinicia)
CODE_MODE_USERS: set[int] = set()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def load_personality() -> str:
    """Lee helion_personalidad.txt (editable sin tocar código ni reiniciar)."""
    if os.path.exists(PERSONALITY_FILE):
        with open(PERSONALITY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    return (
        "Eres Helion, el asistente de IA de este servidor de Discord. "
        "Responde de forma amigable, cercana y breve, en español."
    )


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


def looks_like_moderation_request(text: str) -> bool:
    lowered = text.lower()
    return any(v in lowered for v in MODERATION_VERBS) and any(n in lowered for n in MODERATION_NOUNS)


async def ask_ai(prompt: str, user_id=None) -> str:
    if user_id is not None and user_id in CODE_MODE_USERS:
        system_prompt = CODING_SYSTEM_PROMPT
    else:
        system_prompt = load_personality()
    return await ai_backend.ask(system_prompt, prompt)


# ---------------------------------------------------------------------------
# Formulario (modal) para escribir un mensaje antes de aplicar la sanción
# ---------------------------------------------------------------------------

class ModerationActionModal(discord.ui.Modal):
    def __init__(self, parent_view: "ModerationDecisionView", action_label: str):
        super().__init__(title=f"{action_label}: {parent_view.author_name}")
        self.parent_view = parent_view
        self.action_label = action_label
        self.mensaje_input = discord.ui.InputText(
            label="Mensaje para el usuario (opcional)",
            style=discord.InputTextStyle.long,
            required=False,
            placeholder="Déjalo vacío para usar un mensaje por defecto",
        )
        self.add_item(self.mensaje_input)

    async def callback(self, interaction: discord.Interaction):
        mensaje = self.mensaje_input.value.strip() if self.mensaje_input.value else None
        await self.parent_view.apply_action(interaction, self.action_label, mensaje)


# ---------------------------------------------------------------------------
# Vista con los botones de decisión (Aviso / Expulsar / Banear)
# ---------------------------------------------------------------------------

class ModerationDecisionView(discord.ui.View):
    """
    Se envía por DM a cada administrador en MOD_USER_IDS. El primero que
    pulse un botón abre un formulario para escribir un mensaje, y al
    confirmarlo se aplica la acción. Se marca como resuelto en ambos DMs
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

    def _get_member(self) -> discord.Member | None:
        guild = bot.get_guild(self.guild_id)
        return guild.get_member(self.author_id) if guild else None

    async def _open_modal_if_allowed(self, interaction: discord.Interaction, action_label: str):
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
        await interaction.response.send_modal(ModerationActionModal(self, action_label))

    async def apply_action(self, interaction: discord.Interaction, action_label: str, mensaje: str | None):
        if self.resolved:
            await interaction.response.send_message("Ya se resolvió este caso.", ephemeral=True)
            return
        self.resolved = True

        guild = bot.get_guild(self.guild_id)
        member = self._get_member()
        mod_name = str(interaction.user)
        texto_usuario = mensaje or DEFAULT_ACTION_MESSAGES[action_label]

        try:
            if member:
                await member.send(
                    f"📋 **{action_label}** en **{self.guild_name}**\n"
                    f"Motivo: {self.reason}\n"
                    f"Mensaje del moderador ({mod_name}): {texto_usuario}"
                )
            if action_label == "Expulsión" and member and guild:
                await guild.kick(member, reason=f"Helion - {mod_name}: {self.reason}")
            elif action_label == "Baneo permanente" and member and guild:
                await guild.ban(member, reason=f"Helion - {mod_name}: {self.reason}")

            result_text = (
                f"\n\n✅ **{action_label}** aplicado por {mod_name}.\n"
                f"Mensaje enviado al usuario: \"{texto_usuario}\""
            )
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

    @discord.ui.button(label="Aviso", style=discord.ButtonStyle.secondary, emoji="⚠️")
    async def warn_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal_if_allowed(interaction, "Aviso")

    @discord.ui.button(label="Expulsar", style=discord.ButtonStyle.primary, emoji="👢")
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal_if_allowed(interaction, "Expulsión")

    @discord.ui.button(label="Banear", style=discord.ButtonStyle.danger, emoji="⛔")
    async def ban_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal_if_allowed(interaction, "Baneo permanente")


# ---------------------------------------------------------------------------
# Escaneo del servidor
# ---------------------------------------------------------------------------

async def notify_admins(guild: discord.Guild, author: discord.Member, reason: str,
                         channel_name: str, content_snippet: str):
    view = ModerationDecisionView(guild.id, guild.name, author.id, str(author), reason)
    text = (
        f"🚨 **Posible amenaza detectada en {guild.name}**\n"
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
            f"✅ Revisé el servidor y no encontré nada raro. "
            f"¡Gracias por reportar, {requested_by.mention}!"
        )
    return (
        f"🚨 Se encontró **{incidents}** posible(s) amenaza(s) "
        f"(se eliminaron {deleted} mensaje(s)). "
        f"¡Gracias por reportar, {requested_by.mention}! Ya avisé a los "
        f"administradores para que decidan qué hacer."
    )


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    print(f"✅ Conectado como {bot.user} (ID: {bot.user.id})")
    bot.loop.create_task(youtube_announcer.start_loop(bot))
    bot.loop.create_task(tiktok.start_loop(bot))


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    is_mentioned = bot.user in message.mentions
    is_listen_channel = message.channel.id == LISTEN_CHANNEL_ID

    if not is_mentioned and not is_listen_channel:
        await bot.process_commands(message)
        return

    content = strip_mention(message.content, bot.user.id) if is_mentioned else message.content
    lowered = content.lower()

    if is_mentioned and any(t in lowered for t in CODING_OFF_TRIGGERS):
        CODE_MODE_USERS.discard(message.author.id)
        await message.reply("🔧 Modo código **desactivado**. Vuelvo a ser Helion normal contigo.", mention_author=False)
        return

    if is_mentioned and any(t in lowered for t in CODING_ON_TRIGGERS):
        CODE_MODE_USERS.add(message.author.id)
        await message.reply("💻 Modo código **activado** para ti. A partir de ahora te ayudo como asistente de programación.", mention_author=False)
        return

    if is_mentioned and lowered.startswith(tuple(MUSIC_TRIGGERS)):
        remainder = content
        for trig in MUSIC_TRIGGERS:
            if lowered.startswith(trig):
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

    if is_mentioned and any(trigger in lowered for trigger in JOIN_CALL_TRIGGERS):
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

    if is_mentioned and any(trigger in lowered for trigger in LEAVE_CALL_TRIGGERS):
        if message.guild.voice_client:
            await voice.leave_call(message.guild)
            await message.reply("👋 Salí de la llamada.", mention_author=False)
        else:
            await message.reply("No estoy en ninguna llamada ahora mismo.", mention_author=False)
        return

    if is_mentioned and looks_like_moderation_request(content):
        if not isinstance(message.author, discord.Member) or not user_can_moderate(message.author):
            await message.reply(
                "🔒 Solo un moderador puede pedirme que revise el servidor.",
                mention_author=False,
            )
            return

        await message.reply(
            "🔍 Entendido, revisando el servidor... esto puede tardar un momento.",
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
# Slash commands: /coding, /join, /play
# ---------------------------------------------------------------------------

@bot.slash_command(name="coding", description="Activa o desactiva el modo código para ti")
async def coding_cmd(ctx: discord.ApplicationContext):
    uid = ctx.author.id
    if uid in CODE_MODE_USERS:
        CODE_MODE_USERS.discard(uid)
        await ctx.respond("🔧 Modo código **desactivado**. Vuelvo a ser Helion normal contigo.", ephemeral=True)
    else:
        CODE_MODE_USERS.add(uid)
        await ctx.respond("💻 Modo código **activado** para ti. Te responderé como asistente de programación.", ephemeral=True)


@bot.slash_command(name="join", description="Me uno a tu canal de voz")
async def join_cmd(ctx: discord.ApplicationContext):
    if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
        await ctx.respond("❌ Necesitas estar en un canal de voz.", ephemeral=True)
        return
    vc = await voice.join_call(ctx.author)
    if vc is None:
        await ctx.respond("❌ No pude unirme a tu canal de voz.", ephemeral=True)
        return
    await ctx.respond(f"🔊 Me uní a **{vc.channel.name}**.")


@bot.slash_command(name="leave", description="Salgo de la llamada de voz")
async def leave_cmd(ctx: discord.ApplicationContext):
    if ctx.guild and ctx.guild.voice_client:
        await voice.leave_call(ctx.guild)
        await ctx.respond("👋 Salí de la llamada.")
    else:
        await ctx.respond("No estoy en ninguna llamada ahora mismo.", ephemeral=True)


@bot.slash_command(name="play", description="Reproduce música (aleatoria si no pones nada)")
async def play_cmd(
    ctx: discord.ApplicationContext,
    query: discord.Option(str, description="Link de YouTube o nombre de la canción", required=False) = None,
):
    if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
        await ctx.respond("❌ Necesitas estar en un canal de voz.", ephemeral=True)
        return

    await ctx.respond("🎵 Buscando música, dame un segundo...")
    title, view = await music.start_playback(ctx.author, query)
    if title is None:
        await ctx.followup.send("❌ No pude reproducir eso, intenta con otra cosa.")
        return
    await ctx.followup.send(f"▶️ Reproduciendo: **{title}**", view=view)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("Falta DISCORD_TOKEN en el archivo .env")
    bot.run(DISCORD_TOKEN)
