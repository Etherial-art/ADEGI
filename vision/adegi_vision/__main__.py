"""Entry point: `python -m adegi_vision --backend ultralytics --source 0 ...`

Prints one `person_state` JSON event per processed frame to stdout (JSON lines), so any
consumer (behaviour state machine, app bridge) can read it through a pipe or socket.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from .backends import BACKENDS, create_backend
from .pipeline import PipelineConfig, VisionPipeline, person_state_event
from .posture_mlp import PostureMLP


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ADEGI vision loop")
    p.add_argument("--backend", choices=BACKENDS, default="ultralytics")
    p.add_argument("--local-backend", choices=("ultralytics", "stai_mpu"), default="ultralytics",
                   help="fallback used by --backend jetson when the Jetson is unreachable")
    p.add_argument("--source", default="0",
                   help="camera index, video file, or a GStreamer pipeline string (needs OpenCV built with GStreamer)")
    p.add_argument("--det-model", required=True, help="detector weights (.pt / .tflite / .nb)")
    p.add_argument("--pose-model", required=True, help="pose weights (.pt / .tflite / .nb)")
    p.add_argument("--posture-model", required=True, help="posture MLP .npz")
    p.add_argument("--imgsz", type=int, default=256)
    p.add_argument("--detector-every", type=int, default=4, help="run the detector every N frames")
    p.add_argument("--fall-hold-s", type=float, default=3.0)
    p.add_argument("--jetson-host", default="127.0.0.1")
    p.add_argument("--jetson-port", type=int, default=5600)
    p.add_argument("--jetson-tasks", default="detect,pose", help="comma list of tasks to offload")
    p.add_argument("--max-frames", type=int, default=0, help="0 = run until the source ends")
    p.add_argument("--log-level", default="INFO")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    import cv2  # lazy: keeps `--help` and the unit tests free of the OpenCV import

    backend = create_backend(
        args.backend, det_model=args.det_model, pose_model=args.pose_model, imgsz=args.imgsz,
        jetson_host=args.jetson_host, jetson_port=args.jetson_port,
        jetson_tasks=frozenset(args.jetson_tasks.split(",")), local=args.local_backend,
    )
    pipe = VisionPipeline(backend, PostureMLP.load(args.posture_model),
                          PipelineConfig(detector_every=args.detector_every, fall_hold_s=args.fall_hold_s))
    cap = cv2.VideoCapture(int(args.source) if args.source.isdigit() else args.source)
    if not cap.isOpened():
        logging.error("cannot open source %r", args.source)
        return 2

    n, t0 = 0, time.monotonic()
    try:
        while args.max_frames == 0 or n < args.max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            result = pipe.process(frame, time.time())
            print(json.dumps(person_state_event(result, time.time())), flush=True)
            n += 1
            if n % 100 == 0:
                logging.info("%.1f FPS effective (%d frames)", n / (time.monotonic() - t0), n)
    finally:
        cap.release()
        backend.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
