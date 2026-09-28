import api
from db import initialize_database, record_event
from fastapi.testclient import TestClient


def test_api_summary_and_esp32_endpoint(tmp_path, monkeypatch):
    database = tmp_path / "api.db"
    initialize_database(database)
    record_event("IN", db_path=database)
    monkeypatch.setattr(api, "DB_PATH", database)

    summary = api.get_summary()
    occupancy = api.get_occupancy()

    assert summary["aforo"] == 1
    assert summary["entradas"] == 1
    assert occupancy["aforo"] == 1
    assert occupancy["permitir_ingreso"] is True

    client = TestClient(api.app)
    assert client.get("/").status_code == 200
    assert client.get("/health").json()["database"] == "ok"
    assert client.get("/api/eventos?limit=10").json()[0]["tipo"] == "IN"
