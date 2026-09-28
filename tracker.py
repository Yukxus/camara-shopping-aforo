"""Detección, seguimiento y conteo desde IP Webcam u otra fuente de video."""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass

from counter import LineCrossingCounter
from db import (
    DB_PATH,
    current_occupancy,
    initialize_database,
    record_event,
    set_tracker_status,
)


@dataclass
class Config:
    source: str
    line_y: int
    offset: int
    width: int
    height: int
    down_is_in: bool
    confidence: float
    model: str
    preview: bool
    retry_seconds: float


def parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Contador de personas con YOLO")
    parser.add_argument(
        "--source",
        default=os.getenv("VIDEO_SOURCE", "http://192.168.1.45:8080/video"),
        help="URL /video de IP Webcam, archivo o índice de webcam (por ejemplo 0)",
    )
    parser.add_argument("--line-y", type=int, default=240)
    parser.add_argument("--offset", type=int, default=25)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--confidence", type=float, default=0.35)
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument(
        "--up-is-in",
        action="store_true",
        help="invierte el sentido: subir en la imagen cuenta como entrada",
    )
    parser.add_argument("--no-preview", action="store_true")
    parser.add_argument("--retry-seconds", type=float, default=3.0)
    args = parser.parse_args()
    if args.width <= 0 or args.height <= 0:
        parser.error("--width y --height deben ser positivos")
    if not 0 <= args.line_y < args.height:
        parser.error("--line-y debe estar dentro de la altura del cuadro")
    if not 0 < args.offset < args.height / 2:
        parser.error("--offset debe ser positivo y menor que la mitad de la altura")
    if args.line_y - args.offset < 0 or args.line_y + args.offset >= args.height:
        parser.error("la línea y su banda deben quedar dentro del cuadro")
    if not 0 < args.confidence <= 1:
        parser.error("--confidence debe estar entre 0 y 1")
    return Config(
        source=args.source,
        line_y=args.line_y,
        offset=args.offset,
        width=args.width,
        height=args.height,
        down_is_in=not args.up_is_in,
        confidence=args.confidence,
        model=args.model,
        preview=not args.no_preview,
        retry_seconds=max(0.5, args.retry_seconds),
    )


def normalize_source(source: str) -> str | int:
    return int(source) if source.isdigit() else source


def open_capture(cv2, source: str | int):
    capture = cv2.VideoCapture(source)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def draw_overlay(cv2, frame, config: Config, occupancy: int, entries: int, exits: int) -> None:
    cv2.line(frame, (0, config.line_y), (config.width, config.line_y), (0, 0, 255), 2)
    cv2.line(
        frame,
        (0, config.line_y - config.offset),
        (config.width, config.line_y - config.offset),
        (180, 180, 180),
        1,
    )
    cv2.line(
        frame,
        (0, config.line_y + config.offset),
        (config.width, config.line_y + config.offset),
        (180, 180, 180),
        1,
    )
    labels = (
        (f"Entradas (sesion): {entries}", (0, 220, 0)),
        (f"Salidas (sesion): {exits}", (0, 80, 255)),
        (f"Aforo actual: {occupancy}", (255, 220, 0)),
    )
    for index, (label, color) in enumerate(labels):
        cv2.putText(
            frame,
            label,
            (10, 30 + index * 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68,
            color,
            2,
        )


def run(config: Config) -> None:
    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as error:
        raise SystemExit(
            "Faltan dependencias. Ejecutá: pip install -r requirements.txt"
        ) from error

    initialize_database(DB_PATH)
    model = YOLO(config.model)
    counter = LineCrossingCounter(
        config.line_y,
        config.offset,
        down_is_in=config.down_is_in,
    )
    source = normalize_source(config.source)
    occupancy = current_occupancy(DB_PATH)
    session_entries = 0
    session_exits = 0
    capture = None
    last_heartbeat = 0.0

    print(f"Base de datos: {DB_PATH}")
    print(f"Fuente de video: {config.source}")
    print("Presioná Q sobre la vista de cámara para finalizar.")

    try:
        while True:
            if capture is None or not capture.isOpened():
                set_tracker_status(False, "Intentando conectar la cámara")
                capture = open_capture(cv2, source)
                if not capture.isOpened():
                    print(f"No se pudo abrir la cámara. Reintento en {config.retry_seconds:.1f}s...")
                    capture.release()
                    time.sleep(config.retry_seconds)
                    continue
                counter.clear_tracks()
                print("Cámara conectada.")

            received, frame = capture.read()
            if not received:
                set_tracker_status(False, "Se perdió la señal de la cámara")
                print("Se perdió la señal. Intentando reconectar...")
                capture.release()
                capture = None
                time.sleep(config.retry_seconds)
                continue

            frame = cv2.resize(frame, (config.width, config.height))
            results = model.track(
                frame,
                persist=True,
                classes=[0],
                tracker="bytetrack.yaml",
                conf=config.confidence,
                verbose=False,
            )
            detections: list[dict] = []
            boxes_result = results[0].boxes
            if boxes_result is not None and boxes_result.id is not None:
                boxes = boxes_result.xyxy.cpu().numpy().astype(int)
                track_ids = boxes_result.id.cpu().numpy().astype(int)
                confidences = boxes_result.conf.cpu().numpy()
                for box, track_id, confidence in zip(boxes, track_ids, confidences):
                    x1, y1, x2, y2 = box
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)
                    detections.append(
                        {
                            "track_id": int(track_id),
                            "cx": cx,
                            "cy": cy,
                            "confianza": float(confidence),
                        }
                    )
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 0), 2)
                    cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)
                    cv2.putText(
                        frame,
                        f"Persona {track_id} {confidence:.0%}",
                        (x1, max(18, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 220, 0),
                        2,
                    )

            for event in counter.update(detections):
                saved = record_event(
                    event["tipo"],
                    track_id=event["track_id"],
                    confidence=event["confianza"],
                    db_path=DB_PATH,
                )
                occupancy = saved["aforo_actual"]
                session_entries += event["tipo"] == "IN"
                session_exits += event["tipo"] == "OUT"
                print(
                    f"[{saved['timestamp']}] {event['tipo']} - aforo: {occupancy} "
                    f"(ID {event['track_id']})"
                )

            now = time.monotonic()
            if now - last_heartbeat >= 5:
                set_tracker_status(True, "Cámara conectada y analizando")
                last_heartbeat = now

            if config.preview:
                draw_overlay(
                    cv2,
                    frame,
                    config,
                    occupancy,
                    session_entries,
                    session_exits,
                )
                cv2.imshow("Contador de personas - Camara Shopping", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        print("Tracker detenido por el usuario.")
    finally:
        set_tracker_status(False, "Tracker detenido")
        if capture is not None:
            capture.release()
        if config.preview:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    run(parse_args())
