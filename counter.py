"""Lógica pura de cruce de línea, separada de OpenCV para poder probarla."""

from __future__ import annotations

from dataclasses import dataclass


ABOVE = -1
IN_BAND = 0
BELOW = 1


@dataclass
class TrackState:
    stable_zone: int
    last_seen_frame: int
    last_event_frame: int = -1_000_000


class LineCrossingCounter:
    def __init__(
        self,
        line_y: int,
        offset: int = 25,
        *,
        down_is_in: bool = True,
        cooldown_frames: int = 10,
        max_missing_frames: int = 90,
    ) -> None:
        if offset <= 0:
            raise ValueError("offset debe ser mayor que cero")
        self.line_y = int(line_y)
        self.offset = int(offset)
        self.down_is_in = down_is_in
        self.cooldown_frames = max(0, int(cooldown_frames))
        self.max_missing_frames = max(1, int(max_missing_frames))
        self.tracks: dict[int, TrackState] = {}
        self.frame_number = 0

    def zone_for(self, y: int) -> int:
        if y <= self.line_y - self.offset:
            return ABOVE
        if y >= self.line_y + self.offset:
            return BELOW
        return IN_BAND

    def update(self, detections: list[dict]) -> list[dict]:
        """Recibe IDs/centroides del tracker y devuelve cruces confirmados."""
        self.frame_number += 1
        events: list[dict] = []

        for detection in detections:
            track_id = int(detection["track_id"])
            y = int(detection["cy"])
            zone = self.zone_for(y)
            state = self.tracks.get(track_id)

            if state is None:
                if zone != IN_BAND:
                    self.tracks[track_id] = TrackState(zone, self.frame_number)
                continue

            state.last_seen_frame = self.frame_number
            if zone == IN_BAND or zone == state.stable_zone:
                continue

            if self.frame_number - state.last_event_frame < self.cooldown_frames:
                continue

            moving_down = state.stable_zone == ABOVE and zone == BELOW
            event_type = "IN" if moving_down == self.down_is_in else "OUT"
            events.append({**detection, "tipo": event_type})
            state.stable_zone = zone
            state.last_event_frame = self.frame_number

        self._prune_stale_tracks()
        return events

    def _prune_stale_tracks(self) -> None:
        expired = [
            track_id
            for track_id, state in self.tracks.items()
            if self.frame_number - state.last_seen_frame > self.max_missing_frames
        ]
        for track_id in expired:
            del self.tracks[track_id]

    def clear_tracks(self) -> None:
        self.tracks.clear()
