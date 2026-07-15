"""
Memoria de Helion, guardada en SQLite (helion_recuerdos.db).

Guarda un resumen corto de cada conversación, asociado al usuario que
habló con el bot. Solo memoriza lo que la gente le dice DIRECTAMENTE al
bot (nunca escucha canales por su cuenta).

Además de recordar por ID exacto, permite buscar por nombre — así, si
alguien pregunta "¿qué recuerdas de Fulano?", el bot puede encontrar los
recuerdos de esa persona aunque no la mencione con @.

Cualquiera puede borrar lo que Helion recuerda de sí mismo pidiéndolo
(ver /olvidame en bot.py).
"""

import datetime
import sqlite3
import threading

DB_PATH = "helion_recuerdos.db"
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _init():
    with _connect() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS recuerdos (
                user_id TEXT, username TEXT, fecha TEXT, resumen TEXT
            )"""
        )


_init()


def recordar(user_id, k: int = 5) -> list[str]:
    """Devuelve los k resúmenes más recientes de ese usuario."""
    with _lock, _connect() as con:
        cur = con.execute(
            "SELECT resumen FROM recuerdos WHERE user_id = ? ORDER BY fecha DESC LIMIT ?",
            (str(user_id), k),
        )
        return [row[0] for row in cur.fetchall()]


def guardar(user_id, username: str, resumen: str):
    """Inserta un resumen nuevo con la fecha de hoy."""
    fecha = datetime.datetime.utcnow().isoformat()
    with _lock, _connect() as con:
        con.execute(
            "INSERT INTO recuerdos (user_id, username, fecha, resumen) VALUES (?, ?, ?, ?)",
            (str(user_id), username, fecha, resumen),
        )
        con.commit()


def olvidar(user_id):
    """Borra todo lo que se recuerda de ese usuario."""
    with _lock, _connect() as con:
        con.execute("DELETE FROM recuerdos WHERE user_id = ?", (str(user_id),))
        con.commit()


def buscar_por_nombre(nombre: str, k: int = 5) -> list[tuple[str, list[str]]]:
    """
    Busca usuarios cuyo nombre coincida (parcial, sin importar mayúsculas)
    y devuelve [(nombre_encontrado, [resúmenes]), ...].
    """
    nombre = nombre.strip()
    if len(nombre) < 3:
        return []  # evita búsquedas demasiado genéricas/ruidosas

    with _lock, _connect() as con:
        cur = con.execute(
            "SELECT DISTINCT user_id, username FROM recuerdos WHERE username LIKE ?",
            (f"%{nombre}%",),
        )
        matches = cur.fetchall()

    resultados = []
    for user_id, username in matches:
        resumenes = recordar(user_id, k)
        if resumenes:
            resultados.append((username, resumenes))
    return resultados
