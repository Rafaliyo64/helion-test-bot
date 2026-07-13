# Helion Bot

Bot de Discord con chat de IA, música, voz en llamadas, moderación
asistida por administradores, y un "modo código" para programar.

## Qué hace

### 1. Chat con IA
Menciona al bot (`@Helion hola, ¿cómo estás?`) en cualquier canal y te
responde usando IA. Su personalidad vive en `helion_personalidad.txt`
— editable sin tocar código ni reiniciar el bot.

### 2. Canal de escucha automática
En el canal configurado en `LISTEN_CHANNEL_ID`, el bot responde a
**todos** los mensajes sin necesidad de mencionarlo.

### 3. Modo código
Dile `@Helion activa el modo codigo` (o usa `/coding`) y a partir de
ahí te responde como un asistente de programación experto en vez de
con su personalidad normal — hasta que le digas
`@Helion desactiva el modo codigo` o vuelvas a usar `/coding`
(funciona como interruptor).

### 4. Música
- `@Helion reproduce musica` o `/play` (sin nada) → reproduce algo
  aleatorio.
- `@Helion reproduce <link o nombre>` o `/play <link o nombre>` →
  reproduce eso específico (si no es un link, lo busca por nombre).

En ambos casos, el bot se conecta solo a tu canal de voz y manda un
mensaje con 3 botones:
- **⏪ -10s** — retrocede 10 segundos
- **+10s ⏩** — adelanta 10 segundos
- **⏭️ Skip** — salta a otra canción aleatoria

Usa `yt-dlp` para extraer el audio (funciona con YouTube y otras
fuentes soportadas). Requiere **ffmpeg** instalado.

### 5. Voz en llamadas (EXPERIMENTAL)
`@Helion únete a la llamada` o `/join` conecta al bot a tu canal de
voz. Una vez ahí, di **"Hey Helion, ..."** seguido de lo que quieras
preguntarle y te responde por voz. `@Helion sal de la llamada` o
`/leave` para desconectarlo.

⚠️ Esta es la parte menos estable del bot — usa py-cord (discord.py no
soporta oficialmente recibir audio), graba en ciclos de ~5 segundos y
transcribe con Whisper localmente, así que frases cortadas entre
ciclos pueden no reconocerse bien, y la respuesta no es instantánea.

### 6. Moderación asistida
Si mencionas al bot pidiéndole revisar el servidor o la actividad
(ej. `@Helion revisa la actividad del servidor`, `@Helion escanea el
server`), y **tienes permiso de moderación** (kick/ban, o el rol
configurado en `MOD_ROLE_NAME`):

1. El bot escanea mensajes recientes de todos los canales buscando:
   enlaces de invitación sospechosos, estafas de "nitro gratis",
   enlaces acortados, menciones masivas, spam en mayúsculas, y **malas
   palabras** (lista editable en `malas_palabras.txt` o la variable
   `BAD_WORDS_FILE`).
2. Borra los mensajes que encuentra.
3. Responde en el canal agradeciendo el reporte y contando si se
   encontró algo o no.
4. Manda un **DM a cada administrador** configurado en `MOD_USER_IDS`
   con los detalles del caso (usuario, canal, motivo, fragmento del
   mensaje) y 3 botones: **Aviso**, **Expulsar**, **Banear**.
5. Al pulsar un botón, se abre un **formulario** donde el admin puede
   escribir un mensaje personalizado para el usuario (opcional).
6. Al confirmar, se aplica la acción, y el usuario afectado recibe un
   DM contándole qué pasó, el mensaje del moderador, y quién tomó la
   decisión. El otro DM (al segundo admin) se actualiza también para
   que no se apliquen dos acciones distintas por error.

⚠️ **Solo quien tenga permiso de moderación puede activar el
escaneo** — esto evita que cualquier miembro use al bot para intentar
perjudicar a otros. Pero la sanción final siempre la decide uno de los
administradores configurados, nunca el bot solo.

## El "cerebro" de Helion: Groq (nube) u Ollama (local)

La variable `AI_BACKEND` decide qué usa el bot para pensar:

- **`AI_BACKEND=groq`** (por defecto, recomendado): usa la API
  gratuita de Groq por internet. Funciona bien en cualquier hosting,
  incluido Railway con pocos recursos.
- **`AI_BACKEND=ollama`**: usa [Ollama](https://ollama.com) corriendo
  **en la misma máquina** que el bot, sin nube ni terceros. Requiere
  bastante RAM/CPU — no recomendado en hostings gratuitos/ligeros
  como Railway, pensado para tu propio PC o servidor dedicado.

## Instalación

1. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
   La primera vez tardará más porque `openai-whisper` instala PyTorch.

2. Copia `.env.example` a `.env` y rellena tus valores:
   ```bash
   cp .env.example .env
   ```
   - `DISCORD_TOKEN`: Developer Portal de Discord → tu aplicación → Bot → Reset Token
   - `GROQ_API_KEY`: consigue una gratis en https://console.groq.com

3. Activa en el Developer Portal (Bot → Privileged Gateway Intents):
   **Message Content Intent** y **Server Members Intent**.

4. Dale al bot estos permisos al invitarlo: leer/enviar mensajes,
   gestionar mensajes (para borrar), expulsar miembros, banear
   miembros, leer historial, conectar y hablar en voz.

5. Necesitas **ffmpeg** instalado en el sistema (Ubuntu/Debian:
   `sudo apt install ffmpeg`).

6. Corre el bot:
   ```bash
   python bot.py
   ```

Los comandos slash (`/coding`, `/join`, `/leave`, `/play`) pueden
tardar hasta una hora en aparecer la primera vez en Discord — es
normal, luego quedan instantáneos.

## Despliegue 24/7

Necesitas un servidor/VPS corriendo el script continuamente. Opciones
sencillas: Railway, Render, Fly.io, o un VPS propio (Oracle Cloud free
tier, DigitalOcean, etc.).

## Seguridad del token

- Nunca compartas tu `DISCORD_TOKEN` ni tu `GROQ_API_KEY` con nadie ni
  los subas a un repositorio público.
- El archivo `.env` debe quedar fuera de git — agrégalo a tu
  `.gitignore`.
- Si algún token se filtra, regénéralo inmediatamente desde su panel
  correspondiente.
