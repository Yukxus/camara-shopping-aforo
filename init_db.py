"""Inicializa la base. Los datos sólo se borran con --reset."""

from __future__ import annotations

import argparse

from db import DB_PATH, get_connection, initialize_database, record_event


def main() -> None:
    parser = argparse.ArgumentParser(description="Preparar la base del contador")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="borra todos los eventos existentes antes de iniciar",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="agrega una secuencia pequeña de datos para probar el dashboard",
    )
    args = parser.parse_args()

    initialize_database(DB_PATH)
    if args.reset:
        with get_connection(DB_PATH) as connection:
            connection.execute("DELETE FROM eventos")

    if args.demo:
        for event_type in ("IN", "IN", "IN", "OUT", "IN"):
            record_event(event_type, source="demo", db_path=DB_PATH)

    print(f"[OK] Base lista en: {DB_PATH}")


if __name__ == "__main__":
    main()
