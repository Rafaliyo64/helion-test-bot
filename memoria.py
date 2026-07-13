"""
Memoria de Helion por usuario, guardada en SQLite (helion_memoria.db).

Solo guarda resúmenes de lo que la gente le dice DIRECTAMENTE al bot
(nunca escucha canales por su cuenta), y cualquiera puede borrar lo que
Helion recuerda de él con el comando /olvidame.
"""

import datetime
import sqlite3
import threading

DB_PATH = "helion_memoria.db"
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _init():
    with _connect() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS recuerdos (
                user_id TEXT, fecha TEXT, resumen TEXT
            )"""
        )


_init()


def recordar(user_id, k: int = 3) -> list[str]:
    """Devuelve los k resúmenes más recientes de ese usuario."""
    with _lock, _connect() as con:
        cur = con.execute(
            "SELECT resumen FROM recuerdos WHERE user_id = ? ORDER BY fecha DESC LIMIT ?",
            (str(user_id), k),
        )
        return [row[0] for row in cur.fetchall()]


def guardar(user_id, resumen: str):
    """Inserta un resumen nuevo con la fecha de hoy."""
    fecha = datetime.datetime.utcnow().isoformat()
    with _lock, _connect() as con:
        con.execute(
            "INSERT INTO recuerdos (user_id, fecha, resumen) VALUES (?, ?, ?)",
            (str(user_id), fecha, resumen),
        )
        con.commit()


def olvidar(user_id):
    """Borra todo lo que se recuerda de ese usuario."""
    with _lock, _connect() as con:
        con.execute("DELETE FROM recuerdos WHERE user_id = ?", (str(user_id),))
        con.commit()
