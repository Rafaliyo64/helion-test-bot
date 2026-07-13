# Helion Bot

Bot de Discord con chat de IA integrado y moderación automática.

## Qué hace

1. **Chat con IA**: menciona al bot (`@Helion hola, ¿cómo estás?`) en
   cualquier canal y te responde usando IA (Claude), como si fuera un
   miembro más del server.

2. **Canal de escucha automática**: en el canal configurado
   (`LISTEN_CHANNEL_ID`), el bot responde a **todos** los mensajes sin
   necesidad de mencionarlo. (Nota: escuchar y responder por **voz** en
   una llamada no es viable de forma estable con las librerías actuales
   de Discord, por eso se implementó esta alternativa por texto.)

3. **Moderación semi-automática**: un moderador (alguien con permiso de
   kick/ban, o el rol que definas en `MOD_ROLE_NAME`) menciona al bot y
   le dice algo como *"revisa el server"*. El bot escanea los mensajes
   recientes de todos los canales buscando actividad sospechosa
   (enlaces de invitación, scams de "nitro gratis", enlaces acortados,
   menciones masivas, spam en mayúsculas), **borra el mensaje** si lo
   encuentra, y:
   - Manda un resumen al canal donde se pidió el escaneo (si se
     encontraron amenazas o no).
   - Manda un **DM a cada administrador** configurado en `MOD_USER_IDS`
     explicando el caso (usuario, canal, motivo, fragmento del
     mensaje), con **3 botones**: `Aviso`, `Expulsar`, `Banear`. El
     primer admin que pulse un botón decide la sanción; se marca como
     resuelto en ambos DMs para que no se apliquen dos acciones
     distintas por error.

   ⚠️ **Solo moderadores pueden activar el escaneo**, para evitar que
   cualquier miembro use al bot para intentar reportar/perjudicar a
   otros sin que el staff se entere. Pero la sanción final la deciden
   siempre los administradores configurados en `MOD_USER_IDS` — el bot
   nunca expulsa ni banea sin que un admin lo apruebe.

4. **Unirse a llamadas de voz (EXPERIMENTAL)**: dile
   `@Helion únete a la llamada` estando tú conectado a un canal de voz, y
   el bot se conecta. Una vez ahí, di **"Hey Helion, ..."** seguido de lo
   que quieras preguntarle, y te responde por voz. Para que se vaya,
   dile `@Helion sal de la llamada`.

   ⚠️ **Esta es la parte menos estable del bot.** Discord no tiene una
   forma oficial de recibir audio en discord.py, así que esto usa
   **py-cord** (un fork compatible) y su sistema de grabación. Además:
   - Graba en ciclos de ~5 segundos y luego transcribe — no es un
     reconocimiento fluido en tiempo real, así que frases que queden
     "cortadas" entre un ciclo y otro pueden no reconocerse bien.
   - La transcripción usa **Whisper** corriendo localmente en el
     servidor (sin costo de API, pero necesita más CPU/RAM que el resto
     del bot — con el modelo "base" debería andar bien en casi
     cualquier VPS moderno, pero si notas que tarda mucho, puedes
     cambiar `WHISPER_MODEL=tiny` en tu `.env` para que sea más rápido
     aunque menos preciso).
   - La respuesta por voz usa **gTTS** (texto a voz de Google), que
     necesita que el servidor tenga internet — normal en cualquier
     hosting, no debería ser un problema.
   - Necesitas tener **ffmpeg** instalado en el sistema (en Ubuntu/Debian:
     `sudo apt install ffmpeg`).

5. **Música**: `@Helion reproduce musica` reproduce algo aleatorio.
   `@Helion reproduce <link de YouTube o nombre de canción>` reproduce
   eso específico (si no es un link, lo busca por nombre). El bot se
   conecta solo al canal de voz donde estés, y manda un mensaje con 3
   botones:
   - **⏪ -10s** — retrocede 10 segundos
   - **+10s ⏩** — adelanta 10 segundos
   - **⏭️ Skip** — salta a otra canción aleatoria

   Usa `yt-dlp` para extraer el audio, así que funciona con enlaces de
   YouTube (y varias otras fuentes que soporta yt-dlp). También
   requiere **ffmpeg** instalado.

6. **Personalidad editable**: todo lo que Helion "es" vive en
   `helion_personalidad.txt` — lo puedes editar sin tocar nada de
   código, ni reiniciar el bot (se relee en cada mensaje).

7. **Memoria por persona**: Helion recuerda un resumen corto de tus
   últimas conversaciones con él (guardado en `helion_memoria.db`,
   SQLite local). Solo recuerda lo que la gente le dice DIRECTAMENTE a
   él, nunca escucha canales por su cuenta. Cualquiera puede borrar lo
   que recuerda de sí mismo con `/olvidame`.

8. **`/forja`**: muestra el estado real del robot HELION que se está
   construyendo, leyendo el fichero `estado_helion.json`. Edita ese
   fichero a mano (sin programar nada) cada vez que avances en el
   taller, y el bot lo refleja tanto en el comando como en su forma de
   hablar en el chat normal.

9. **Sistema de piezas de la comunidad**: cada mensaje con sustancia en
   el server suma una "pieza" a quien lo escribió (con un límite
   anti-spam configurable). `/nucleo` muestra tu progreso por fases
   (Chasis → Voz → Manos → Piernas → Núcleo completo), y `/ranking`
   muestra los constructores más activos.

10. **Anuncios de YouTube**: si configuras `YOUTUBE_CHANNEL_ID` y
    `ANNOUNCE_CHANNEL_ID`, el bot revisa el canal de YouTube cada 10
    minutos (configurable) y anuncia solo cuando sale un video nuevo,
    usando el RSS gratuito de YouTube (sin API key).

## El "cerebro" de Helion: Groq (nube) u Ollama (local)

La variable `AI_BACKEND` en tu `.env` decide qué usa el bot para pensar:

- **`AI_BACKEND=groq`** (por defecto): usa la API gratuita de Groq por
  internet. Funciona bien en cualquier hosting, incluido Railway con
  pocos recursos. **Recomendado si alojas el bot en la nube.**
- **`AI_BACKEND=ollama`**: usa [Ollama](https://ollama.com) corriendo
  **en la misma máquina** que el bot, sin nube ni terceros. Necesitas
  instalar Ollama ahí y descargar un modelo (`ollama pull qwen2.5:7b`,
  o `llama3.2:3b` si la máquina es más modesta). **Esto requiere
  bastante RAM/CPU — no funciona bien en el plan gratuito de Railway u
  otros hostings ligeros.** Está pensado para tu propio PC encendido
  24/7, o un VPS propio con recursos de sobra.

Puedes empezar con Groq (ya lo tienes funcionando en Railway) y más
adelante, si montas tu propio servidor con más recursos, cambiar a
Ollama simplemente editando esta variable — el resto del bot no
cambia.

## Instalación

1. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
   La primera vez tardará un poco más porque `openai-whisper` instala
   PyTorch. Si tu VPS es muy limitado en RAM, esto puede ser pesado —
   avísame si quieres una alternativa más liviana (por ejemplo,
   `faster-whisper` o desactivar la función de voz por completo).

2. Copia `.env.example` a `.env` y rellena tus valores:
   ```bash
   cp .env.example .env
   ```
   - `DISCORD_TOKEN`: Developer Portal de Discord → tu aplicación → Bot → Reset Token
   - `GROQ_API_KEY`: consigue una gratis en https://console.groq.com (sin tarjeta, solo cuenta de correo o Google)
   - `LISTEN_CHANNEL_ID`: ya viene puesto con el canal que diste
   - `MOD_ROLE_NAME`: opcional, nombre exacto de un rol adicional que
     también pueda activar la moderación

3. **Activa los "Privileged Gateway Intents"** en el Developer Portal
   (Bot → Privileged Gateway Intents): activa **Message Content Intent**
   y **Server Members Intent**. Sin esto el bot no puede leer el
   contenido de los mensajes ni la lista de miembros.

4. Dale al bot los permisos necesarios al invitarlo al server:
   - Leer/enviar mensajes
   - Gestionar mensajes (para poder borrar)
   - Expulsar miembros
   - Banear miembros
   - Leer historial de mensajes

5. Corre el bot:
   ```bash
   python bot.py
   ```

## Despliegue 24/7

Para que el bot esté siempre conectado necesitas un servidor/VPS
corriendo el script continuamente (tu PC apagada = bot desconectado).
Opciones sencillas y gratuitas/baratas: Railway, Render, Fly.io, o un
VPS pequeño (ej. Oracle Cloud free tier, DigitalOcean). Si quieres, te
explico paso a paso cómo desplegarlo en cualquiera de esas.

## Seguridad del token

- Nunca compartas tu `DISCORD_TOKEN` ni tu `GROQ_API_KEY` con
  nadie ni los subas a un repositorio público.
- El archivo `.env` ya está pensado para quedar fuera de git — si usas
  git, agrégalo a tu `.gitignore`.
- Si algún token se filtra, regénéralo inmediatamente desde su panel
  correspondiente.
