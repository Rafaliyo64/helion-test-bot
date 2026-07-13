"""
Sistema de piezas: cada mensaje con sustancia suma una pieza al "núcleo"
de quien lo escribió. Guardado en SQLite (helion_piezas.db).

Anti-trampas:
  - Mensajes de menos de MIN_CHARS caracteres no cuentan.
  - Máximo MAX_PIEZAS_POR_HORA piezas por usuario por hora.
"""

import datetime
import os
import sqlite3
import threading

DB_PATH = "helion_piezas.db"
_lock = threading.Lock()

MIN_CHARS = int(os.getenv("PIEZAS_MIN_CHARS", "8"))
MAX_PIEZAS_POR_HORA = int(os.getenv("PIEZAS_MAX_POR_HORA", "3"))
PIEZAS_POR_FASE = int(os.getenv("PIEZAS_POR_FASE", "10"))

FASES = ["Chasis", "Voz", "Manos", "Piernas", "Núcleo completo"]


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _init():
    with _connect() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS piezas (
                user_id TEXT, tipo TEXT, fecha TEXT
            )"""
        )


_init()


def _piezas_ultima_hora(user_id) -> int:
    hace_una_hora = (datetime.datetime.utcnow() - datetime.timedelta(hours=1)).isoformat()
    with _connect() as con:
        cur = con.execute(
            "SELECT COUNT(*) FROM piezas WHERE user_id = ? AND fecha > ?",
            (str(user_id), hace_una_hora),
        )
        return cur.fetchone()[0]


def registrar_mensaje(user_id, contenido: str) -> bool:
    """
    Intenta sumar una pieza por un mensaje con sustancia.
    Devuelve True si se sumó, False si no cumplió los requisitos.
    """
    if len(contenido.strip()) < MIN_CHARS:
        return False

    with _lock:
        if _piezas_ultima_hora(user_id) >= MAX_PIEZAS_POR_HORA:
            return False
        with _connect() as con:
            con.execute(
                "INSERT INTO piezas (user_id, tipo, fecha) VALUES (?, ?, ?)",
                (str(user_id), "mensaje", datetime.datetime.utcnow().isoformat()),
            )
            con.commit()
    return True


def total_piezas(user_id) -> int:
    with _connect() as con:
        cur = con.execute("SELECT COUNT(*) FROM piezas WHERE user_id = ?", (str(user_id),))
        return cur.fetchone()[0]


def fase_actual(user_id) -> tuple[str, int, int]:
    """Devuelve (nombre_de_fase, piezas_actuales, piezas_para_la_siguiente_fase)."""
    total = total_piezas(user_id)
    idx = min(total // PIEZAS_POR_FASE, len(FASES) - 1)
    piezas_para_siguiente = (idx + 1) * PIEZAS_POR_FASE
    return FASES[idx], total, piezas_para_siguiente


def ranking(top_n: int = 10) -> list[tuple[str, int]]:
    with _connect() as con:
        cur = con.execute(
            "SELECT user_id, COUNT(*) as c FROM piezas GROUP BY user_id ORDER BY c DESC LIMIT ?",
            (top_n,),
        )
        return cur.fetchall()
