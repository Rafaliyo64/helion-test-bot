"""
Anuncia en un canal de Discord cuando sale un video nuevo en un perfil de
TikTok. A diferencia de YouTube, TikTok NO tiene una API pública ni RSS
gratuito, así que esto funciona "raspando" (scraping) la página pública
del perfil.

⚠️ Avisos importantes:
- Esto puede romperse si TikTok cambia la estructura de su página (pasa
  de vez en cuando). Si un día deja de funcionar, probablemente hay que
  actualizar cómo se extrae la información.
- No lo consultes muy seguido (recomendado: cada 10-15 minutos como
  mínimo) o TikTok puede empezar a bloquear las peticiones.
- Solo funciona con perfiles públicos.

Configuración (en tu .env):
  TIKTOK_USERNAME=nombredeusuario         (sin @, o con @, ambos funcionan)
  TIKTOK_ANNOUNCE_CHANNEL_ID=1234567890
  TIKTOK_CHECK_INTERVAL=900               (segundos, 900 = 15 minutos)

Si no configuras TIKTOK_USERNAME o TIKTOK_ANNOUNCE_CHANNEL_ID, esta
función simplemente no hace nada.
"""

import asyncio
import json
import os
import re

import aiohttp

TIKTOK_USERNAME = os.getenv("TIKTOK_USERNAME", "").strip().lstrip("@")
ANNOUNCE_CHANNEL_ID = int(os.getenv("TIKTOK_ANNOUNCE_CHANNEL_ID", "0"))
CHECK_INTERVAL = int(os.getenv("TIKTOK_CHECK_INTERVAL", "900"))  # 15 minutos por defecto

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

_last_video_id: str | None = None


async def _fetch_latest_video() -> dict | None:
    """
    Descarga la página del perfil y extrae el video más reciente del JSON
    embebido que TikTok incluye en el HTML (__UNIVERSAL_DATA_FOR_REHYDRATION__).
    """
    url = f"https://www.tiktok.com/@{TIKTOK_USERNAME}"
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                print(f"[tiktok] La página respondió con status {resp.status}")
                return None
            html = await resp.text()

    match = re.search(
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not match:
        print("[tiktok] No encontré el bloque de datos esperado en la página "
              "(puede que TikTok haya cambiado su estructura).")
        return None

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        print("[tiktok] No pude parsear el JSON de la página.")
        return None

    try:
        scope = data["__DEFAULT_SCOPE__"]["webapp.user-detail"]
        item_list = scope["itemList"]
    except (KeyError, TypeError):
        item_list = None

    if not item_list:
        # A veces el primer video viene en otra ruta del JSON según la región
        try:
            item_list = data["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]["itemList"]
        except (KeyError, TypeError):
            return None

    if not item_list:
        return None

    video = item_list[0]
    video_id = video.get("id")
    desc = video.get("desc", "").strip() or "(sin descripción)"
    if not video_id:
        return None

    return {
        "id": video_id,
        "desc": desc,
        "link": f"https://www.tiktok.com/@{TIKTOK_USERNAME}/video/{video_id}",
    }


async def start_loop(bot):
    """Bucle en segundo plano: revisa el perfil de TikTok cada N segundos."""
    global _last_video_id

    if not TIKTOK_USERNAME or not ANNOUNCE_CHANNEL_ID:
        return  # función desactivada si falta configuración

    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            video = await _fetch_latest_video()
            if video and video["id"] != _last_video_id:
                # El primer video que veamos al arrancar no se anuncia,
                # solo evitamos re-anunciarlo después.
                if _last_video_id is not None:
                    channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
                    if channel:
                        await channel.send(
                            f"🎵 ¡Nuevo TikTok de @{TIKTOK_USERNAME}!\n"
                            f"{video['desc']}\n{video['link']}"
                        )
                _last_video_id = video["id"]
        except Exception as e:
            print(f"[tiktok] Error revisando el perfil: {e}")

        await asyncio.sleep(CHECK_INTERVAL)
