"""
Puente entre Helion (el bot) y HELION (el robot real).

El creador edita estado_helion.json a mano cada vez que avanza en el
taller (sin programar nada). Este módulo lee ese fichero para:
  1. El comando /forja (muestra un embed bonito con el estado).
  2. La personalidad del bot (para que Helion hable de su propio estado
     real en conversación, sin inventar nada).
"""

import json
import os

import discord

ESTADO_PATH = os.getenv("ESTADO_FILE", "estado_helion.json")


def read_estado() -> dict | None:
    if not os.path.exists(ESTADO_PATH):
        return None
    try:
        with open(ESTADO_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def read_estado_text() -> str | None:
    """Versión en texto plano del estado, para inyectar en la personalidad."""
    e = read_estado()
    if not e:
        return None
    return (
        f"Fase actual: {e.get('fase', '?')}. "
        f"Última pieza instalada: {e.get('ultima_pieza', '?')}. "
        f"Ensamblaje: {e.get('ensamblaje', '?')}%. "
        f"Próximo hito: {e.get('proximo_hito', '?')}. "
        f"Actualizado: {e.get('actualizado', '?')}."
    )


def build_embed() -> discord.Embed:
    e = read_estado()
    if not e:
        return discord.Embed(
            title="🔧 Estado de HELION",
            description="Todavía no hay datos (falta el fichero estado_helion.json).",
            color=discord.Color.orange(),
        )

    embed = discord.Embed(title="🔧 Estado actual de HELION", color=discord.Color.blurple())
    embed.add_field(name="Fase", value=str(e.get("fase", "?")), inline=True)
    embed.add_field(name="Ensamblaje", value=f"{e.get('ensamblaje', '?')}%", inline=True)
    embed.add_field(name="Última pieza", value=str(e.get("ultima_pieza", "?")), inline=False)
    embed.add_field(name="Próximo hito", value=str(e.get("proximo_hito", "?")), inline=False)
    embed.set_footer(text=f"Actualizado: {e.get('actualizado', '?')}")
    return embed
