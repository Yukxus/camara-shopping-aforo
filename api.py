"""API y dashboard del contador de personas."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from db import (
    DB_PATH,
    daily_series,
    daily_summary,
    hourly_series,
    initialize_database,
    recent_events,
)


BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_PATH = BASE_DIR / "dashboard.html"
AFORO_MAXIMO = 30

app = FastAPI(title="Shopping People Counter API", version="2.0.0")
initialize_database(DB_PATH)


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(DASHBOARD_PATH)


@app.get("/api/resumen")
def get_summary() -> dict:
    try:
        summary = daily_summary(db_path=DB_PATH)
        summary["maximo"] = AFORO_MAXIMO
        summary["permitir_ingreso"] = summary["aforo"] < AFORO_MAXIMO
        return summary
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Error al leer la base: {error}") from error


@app.get("/api/aforo")
def get_occupancy() -> dict:
    """Endpoint compacto, pensado también para la futura ESP32."""
    summary = get_summary()
    last_event = summary["ultimo_evento"] or {}
    return {
        "aforo": summary["aforo"],
        "maximo": summary["maximo"],
        "ultimo_evento": last_event.get("tipo", "NONE"),
        "timestamp": last_event.get("timestamp"),
        "permitir_ingreso": summary["permitir_ingreso"],
    }


@app.get("/api/eventos")
def get_events(limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
    try:
        return recent_events(limit, db_path=DB_PATH)
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Error al leer la base: {error}") from error


@app.get("/api/series/hora")
def get_hourly_series(fecha: str | None = None) -> list[dict]:
    try:
        return hourly_series(fecha, db_path=DB_PATH)
    except (sqlite3.Error, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/series/dias")
def get_daily_series(dias: int = Query(default=7, ge=1, le=90)) -> list[dict]:
    try:
        return daily_series(dias, db_path=DB_PATH)
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail=f"Error al leer la base: {error}") from error


@app.get("/health")
def health() -> dict:
    try:
        initialize_database(DB_PATH)
        return {"status": "ok", "database": "ok"}
    except sqlite3.Error as error:
        raise HTTPException(status_code=503, detail=f"Base no disponible: {error}") from error
