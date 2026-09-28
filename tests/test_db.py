from db import (
    daily_summary,
    hourly_series,
    initialize_database,
    now_local,
    recent_events,
    record_event,
)


def test_events_are_persistent_and_occupancy_never_becomes_negative(tmp_path):
    database = tmp_path / "test.db"
    initialize_database(database)

    record_event("IN", track_id=10, confidence=0.91, db_path=database)
    record_event("IN", track_id=11, confidence=0.87, db_path=database)
    record_event("OUT", track_id=10, confidence=0.88, db_path=database)
    last = record_event("OUT", track_id=99, db_path=database)
    floor = record_event("OUT", track_id=100, db_path=database)

    assert last["aforo_actual"] == 0
    assert floor["aforo_actual"] == 0
    assert len(recent_events(10, db_path=database)) == 5


def test_summary_and_hourly_series_use_saved_events(tmp_path):
    database = tmp_path / "test.db"
    initialize_database(database)
    timestamp = now_local().replace(hour=14, minute=5, second=0).isoformat()
    record_event("IN", db_path=database, timestamp=timestamp)
    record_event("OUT", db_path=database, timestamp=timestamp)

    summary = daily_summary(db_path=database)
    series = hourly_series(db_path=database)

    assert summary["entradas"] == 1
    assert summary["salidas"] == 1
    assert series[14]["entradas"] == 1
    assert series[14]["salidas"] == 1
