"""
Anuncia en un canal de Discord cuando sale un video nuevo en YouTube,
usando el feed RSS gratuito de YouTube (sin API key, sin cuota).

Se activa solo si configuras YOUTUBE_CHANNEL_ID y ANNOUNCE_CHANNEL_ID
en el .env. Si no, esta función simplemente no hace nada.
"""

import asyncio
import os
import xml.etree.ElementTree as ET

import aiohttp

YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0"))
CHECK_INTERVAL = int(os.getenv("YOUTUBE_CHECK_INTERVAL", "600"))  # 10 minutos

_FEED_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}

_last_video_id: str | None = None


async def _fetch_latest_video() -> dict | None:
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            text = await resp.text()

    root = ET.fromstring(text)
    entry = root.find("atom:entry", _FEED_NS)
    if entry is None:
        return None

    video_id_el = entry.find("yt:videoId", _FEED_NS)
    title_el = entry.find("atom:title", _FEED_NS)
    link_el = entry.find("atom:link", _FEED_NS)
    if video_id_el is None or title_el is None or link_el is None:
        return None

    return {
        "id": video_id_el.text,
        "title": title_el.text,
        "link": link_el.attrib.get("href"),
    }


async def start_loop(bot):
    """Bucle en segundo plano: revisa el canal de YouTube cada N segundos."""
    global _last_video_id

    if not YOUTUBE_CHANNEL_ID or not ANNOUNCE_CHANNEL_ID:
        return  # función desactivada si falta configuración

    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            video = await _fetch_latest_video()
            if video and video["id"] != _last_video_id:
                # No anunciamos el primer video que veamos al arrancar,
                # solo evitamos re-anunciarlo en el próximo ciclo.
                if _last_video_id is not None:
                    channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
                    if channel:
                        await channel.send(
                            f"🎬 ¡Nuevo video en el canal! **{video['title']}**\n{video['link']}"
                        )
                _last_video_id = video["id"]
        except Exception as e:
            print(f"[youtube] Error revisando el canal: {e}")

        await asyncio.sleep(CHECK_INTERVAL)
