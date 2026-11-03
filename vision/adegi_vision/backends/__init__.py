"""Backend factory. Imports are lazy so the board never needs Ultralytics and a PC never needs stai_mpu."""

from __future__ import annotations

from .base import InferenceBackend

BACKENDS = ("ultralytics", "stai_mpu", "jetson")


def create_backend(name: str, *, det_model: str, pose_model: str, imgsz: int = 256,
                   jetson_host: str = "127.0.0.1", jetson_port: int = 5600,
                   jetson_tasks: frozenset[str] = frozenset({"detect", "pose"}),
                   local: str = "ultralytics") -> InferenceBackend:
    """`jetson` wraps a local backend (`local`) that is used whenever the Jetson fails."""
    if name == "ultralytics":
        from .ultralytics_backend import UltralyticsBackend

        return UltralyticsBackend(det_model, pose_model, imgsz=imgsz)
    if name == "stai_mpu":
        from .stai_mpu_backend import StaiMpuBackend

        return StaiMpuBackend(det_model, pose_model)
    if name == "jetson":
        from .jetson_backend import JetsonBackend

        if local == "jetson":
            raise ValueError("--local-backend cannot be 'jetson' (it IS the fallback)")
        fallback = create_backend(local, det_model=det_model, pose_model=pose_model, imgsz=imgsz)
        return JetsonBackend(fallback, jetson_host, jetson_port, tasks=jetson_tasks)
    raise ValueError(f"unknown backend {name!r}; choose from {BACKENDS}")
