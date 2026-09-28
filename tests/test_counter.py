from counter import LineCrossingCounter


def detection(track_id: int, y: int) -> dict:
    return {"track_id": track_id, "cx": 100, "cy": y, "confianza": 0.9}


def test_gradual_downward_crossing_counts_one_entry():
    counter = LineCrossingCounter(240, 25, cooldown_frames=0)

    assert counter.update([detection(1, 190)]) == []
    assert counter.update([detection(1, 225)]) == []
    assert counter.update([detection(1, 245)]) == []
    events = counter.update([detection(1, 270)])

    assert [event["tipo"] for event in events] == ["IN"]


def test_same_track_can_enter_and_then_leave():
    counter = LineCrossingCounter(240, 25, cooldown_frames=0)
    sequence = [190, 240, 270, 240, 190]
    events = []
    for y in sequence:
        events.extend(counter.update([detection(7, y)]))

    assert [event["tipo"] for event in events] == ["IN", "OUT"]


def test_movement_inside_hysteresis_band_does_not_count():
    counter = LineCrossingCounter(240, 25)
    events = []
    for y in [230, 245, 220, 250, 239]:
        events.extend(counter.update([detection(3, y)]))

    assert events == []


def test_direction_can_be_inverted():
    counter = LineCrossingCounter(240, 25, down_is_in=False, cooldown_frames=0)
    counter.update([detection(2, 190)])

    events = counter.update([detection(2, 270)])

    assert events[0]["tipo"] == "OUT"


def test_reverse_crossing_is_delayed_but_not_lost_during_cooldown():
    counter = LineCrossingCounter(240, 25, cooldown_frames=3)
    events = []
    for y in [190, 270, 190, 190, 190]:
        events.extend(counter.update([detection(8, y)]))

    assert [event["tipo"] for event in events] == ["IN", "OUT"]
