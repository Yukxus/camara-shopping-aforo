"""Acceso centralizado a la base SQLite del contador de personas."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SHOPPING_DB_PATH", BASE_DIR / "conteo_local.db"))
try:
    TIMEZONE = ZoneInfo(
        os.getenv("SHOPPING_TIMEZONE", "America/Argentina/Buenos_Aires")
    )
except ZoneInfoNotFoundError:
    # Windows puede no incluir la base IANA. Argentina usa UTC-3 actualmente.
    TIMEZONE = timezone(timedelta(hours=-3), name="ART")

_INITIALIZED_PATHS: set[str] = set()
_INITIALIZE_LOCK = threading.Lock()


def now_local() -> datetime:
    return datetime.now(TIMEZONE)


def now_iso() -> str:
    return now_local().isoformat(timespec="seconds")


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path), timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def _add_missing_columns(connection: sqlite3.Connection) -> None:
    """Actualiza bases creadas por la primera versión sin borrar sus eventos."""
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(eventos)")
    }
    additions = {
        "track_id": "INTEGER",
        "confianza": "REAL",
        "fuente": "TEXT NOT NULL DEFAULT 'camara'",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE eventos ADD COLUMN {name} {definition}")


def initialize_database(db_path: Path | str = DB_PATH) -> None:
    path_key = str(Path(db_path).resolve())
    if path_key in _INITIALIZED_PATHS:
        return

    with _INITIALIZE_LOCK:
        if path_key in _INITIALIZED_PATHS:
            return
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with get_connection(db_path) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS eventos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    tipo TEXT NOT NULL CHECK (tipo IN ('IN', 'OUT', 'RESET')),
                    aforo_actual INTEGER NOT NULL CHECK (aforo_actual >= 0),
                    track_id INTEGER,
                    confianza REAL,
                    fuente TEXT NOT NULL DEFAULT 'camara'
                )
                """
            )
            _add_missing_columns(connection)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_eventos_timestamp ON eventos(timestamp)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_eventos_tipo ON eventos(tipo)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS estado_tracker (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    activo INTEGER NOT NULL DEFAULT 0,
                    ultima_actualizacion TEXT NOT NULL,
                    mensaje TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO estado_tracker
                    (id, activo, ultima_actualizacion, mensaje)
                VALUES (1, 0, ?, 'Todavía no se inició el tracker')
                """,
                (now_iso(),),
            )
        _INITIALIZED_PATHS.add(path_key)


def current_occupancy(db_path: Path | str = DB_PATH) -> int:
    initialize_database(db_path)
    with get_connection(db_path) as connection:
        row = connection.execute(
            "SELECT aforo_actual FROM eventos ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return int(row["aforo_actual"]) if row else 0


def record_event(
    event_type: str,
    *,
    track_id: int | None = None,
    confidence: float | None = None,
    source: str = "camara",
    db_path: Path | str = DB_PATH,
    timestamp: str | None = None,
) -> dict:
    """Registra un cruce y calcula el nuevo aforo de forma atómica."""
    if event_type not in {"IN", "OUT"}:
        raise ValueError("event_type debe ser 'IN' u 'OUT'")

    initialize_database(db_path)
    connection = get_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT aforo_actual FROM eventos ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous = int(row["aforo_actual"]) if row else 0
        occupancy = previous + 1 if event_type == "IN" else max(0, previous - 1)
        event_timestamp = timestamp or now_iso()
        cursor = connection.execute(
            """
            INSERT INTO eventos
                (timestamp, tipo, aforo_actual, track_id, confianza, fuente)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event_timestamp,
                event_type,
                occupancy,
                track_id,
                round(float(confidence), 4) if confidence is not None else None,
                source,
            ),
        )
        connection.commit()
        return {
            "id": cursor.lastrowid,
            "timestamp": event_timestamp,
            "tipo": event_type,
            "aforo_actual": occupancy,
            "track_id": track_id,
            "confianza": confidence,
            "fuente": source,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def reset_occupancy(
    occupancy: int = 0,
    *,
    source: str = "manual",
    db_path: Path | str = DB_PATH,
) -> dict:
    if occupancy < 0:
        raise ValueError("El aforo no puede ser negativo")
    initialize_database(db_path)
    event_timestamp = now_iso()
    with get_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO eventos (timestamp, tipo, aforo_actual, fuente)
            VALUES (?, 'RESET', ?, ?)
            """,
            (event_timestamp, occupancy, source),
        )
    return {
        "id": cursor.lastrowid,
        "timestamp": event_timestamp,
        "tipo": "RESET",
        "aforo_actual": occupancy,
        "fuente": source,
    }


def set_tracker_status(
    active: bool,
    message: str,
    *,
    db_path: Path | str = DB_PATH,
) -> None:
    initialize_database(db_path)
    with get_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO estado_tracker (id, activo, ultima_actualizacion, mensaje)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                activo = excluded.activo,
                ultima_actualizacion = excluded.ultima_actualizacion,
                mensaje = excluded.mensaje
            """,
            (int(active), now_iso(), message[:200]),
        )


def tracker_status(
    *, db_path: Path | str = DB_PATH, stale_after_seconds: int = 15
) -> dict:
    initialize_database(db_path)
    with get_connection(db_path) as connection:
        row = connection.execute(
            "SELECT activo, ultima_actualizacion, mensaje FROM estado_tracker WHERE id = 1"
        ).fetchone()
    if row is None:
        return {"activo": False, "ultima_actualizacion": None, "mensaje": "Sin estado"}

    updated_at = datetime.fromisoformat(row["ultima_actualizacion"])
    is_fresh = now_local() - updated_at.astimezone(TIMEZONE) <= timedelta(
        seconds=stale_after_seconds
    )
    return {
        "activo": bool(row["activo"]) and is_fresh,
        "ultima_actualizacion": row["ultima_actualizacion"],
        "mensaje": row["mensaje"] if is_fresh else "Tracker sin señal reciente",
    }


def recent_events(limit: int = 50, *, db_path: Path | str = DB_PATH) -> list[dict]:
    initialize_database(db_path)
    safe_limit = max(1, min(int(limit), 500))
    with get_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, timestamp, tipo, aforo_actual, track_id, confianza, fuente
            FROM eventos ORDER BY id DESC LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def daily_summary(
    date: str | None = None, *, db_path: Path | str = DB_PATH
) -> dict:
    initialize_database(db_path)
    selected_date = date or now_local().date().isoformat()
    with get_connection(db_path) as connection:
        counts = connection.execute(
            """
            SELECT
                SUM(CASE WHEN tipo = 'IN' THEN 1 ELSE 0 END) AS entradas,
                SUM(CASE WHEN tipo = 'OUT' THEN 1 ELSE 0 END) AS salidas
            FROM eventos WHERE substr(timestamp, 1, 10) = ?
            """,
            (selected_date,),
        ).fetchone()
        last_event = connection.execute(
            """
            SELECT id, timestamp, tipo, aforo_actual, track_id, confianza, fuente
            FROM eventos ORDER BY id DESC LIMIT 1
            """
        ).fetchone()

    return {
        "fecha": selected_date,
        "aforo": int(last_event["aforo_actual"]) if last_event else 0,
        "entradas": int(counts["entradas"] or 0),
        "salidas": int(counts["salidas"] or 0),
        "ultimo_evento": dict(last_event) if last_event else None,
        "tracker": tracker_status(db_path=db_path),
    }


def hourly_series(
    date: str | None = None, *, db_path: Path | str = DB_PATH
) -> list[dict]:
    initialize_database(db_path)
    selected_date = date or now_local().date().isoformat()
    hours = {hour: {"hora": f"{hour:02d}:00", "entradas": 0, "salidas": 0} for hour in range(24)}
    with get_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                CAST(substr(timestamp, 12, 2) AS INTEGER) AS hora,
                SUM(CASE WHEN tipo = 'IN' THEN 1 ELSE 0 END) AS entradas,
                SUM(CASE WHEN tipo = 'OUT' THEN 1 ELSE 0 END) AS salidas
            FROM eventos
            WHERE substr(timestamp, 1, 10) = ? AND tipo IN ('IN', 'OUT')
            GROUP BY hora ORDER BY hora
            """,
            (selected_date,),
        ).fetchall()
    for row in rows:
        hour = int(row["hora"])
        if hour in hours:
            hours[hour]["entradas"] = int(row["entradas"] or 0)
            hours[hour]["salidas"] = int(row["salidas"] or 0)
    return list(hours.values())


def daily_series(days: int = 7, *, db_path: Path | str = DB_PATH) -> list[dict]:
    initialize_database(db_path)
    safe_days = max(1, min(int(days), 90))
    start_date = (now_local().date() - timedelta(days=safe_days - 1)).isoformat()
    with get_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                substr(timestamp, 1, 10) AS fecha,
                SUM(CASE WHEN tipo = 'IN' THEN 1 ELSE 0 END) AS entradas,
                SUM(CASE WHEN tipo = 'OUT' THEN 1 ELSE 0 END) AS salidas
            FROM eventos
            WHERE substr(timestamp, 1, 10) >= ? AND tipo IN ('IN', 'OUT')
            GROUP BY fecha ORDER BY fecha
            """,
            (start_date,),
        ).fetchall()
    by_date = {row["fecha"]: dict(row) for row in rows}
    result = []
    for offset in range(safe_days):
        date = (now_local().date() - timedelta(days=safe_days - 1 - offset)).isoformat()
        row = by_date.get(date, {})
        result.append(
            {
                "fecha": date,
                "entradas": int(row.get("entradas", 0)),
                "salidas": int(row.get("salidas", 0)),
            }
        )
    return result
