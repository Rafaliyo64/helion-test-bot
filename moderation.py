"""
Módulo de detección de mensajes sospechosos de Helion.

La decisión de sanción (aviso / expulsión / baneo) ya NO es automática:
la toma un administrador desde los botones que le llegan por DM
(ver bot.py -> ModerationDecisionView). Este módulo solo se encarga de
detectar si un mensaje es sospechoso y por qué.
"""

import re

# --- Patrones de actividad sospechosa -------------------------------------

SUSPICIOUS_PATTERNS = [
    # Enlaces de invitación a otros servidores (posible raid/spam)
    (re.compile(r"(discord\.gg|discordapp\.com/invite)/\S+", re.IGNORECASE),
     "enlace de invitación a otro servidor"),
    # Estafas clásicas de "nitro gratis"
    (re.compile(r"(free\s*nitro|nitro\s*gratis|steam\s*gift)", re.IGNORECASE),
     "posible estafa de nitro/regalo gratis"),
    # Enlaces acortados frecuentemente usados en phishing
    (re.compile(r"(bit\.ly|tinyurl\.com|grabify\.link|iplogger)", re.IGNORECASE),
     "enlace acortado sospechoso (posible phishing)"),
    # Menciones masivas combinadas con llamada a la acción
    (re.compile(r"(@everyone|@here).{0,20}(click|link|free|gratis)", re.IGNORECASE),
     "uso sospechoso de @everyone/@here junto a un enlace"),
]

MASS_MENTION_THRESHOLD = 6   # más de N menciones en un solo mensaje = sospechoso
CAPS_RATIO_THRESHOLD = 0.8   # % de mayúsculas en mensajes largos = spam/grito
MIN_LEN_FOR_CAPS_CHECK = 15


def is_suspicious(message_content: str, mention_count: int) -> str | None:
    """
    Devuelve una razón (string) si el mensaje es sospechoso, o None si no lo es.
    """
    for pattern, reason in SUSPICIOUS_PATTERNS:
        if pattern.search(message_content):
            return reason

    if mention_count >= MASS_MENTION_THRESHOLD:
        return f"mención masiva sospechosa ({mention_count} menciones en un mensaje)"

    if len(message_content) >= MIN_LEN_FOR_CAPS_CHECK:
        letters = [c for c in message_content if c.isalpha()]
        if letters:
            caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            if caps_ratio >= CAPS_RATIO_THRESHOLD:
                return "spam en mayúsculas"

    return None
