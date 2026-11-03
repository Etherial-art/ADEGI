# Copilot instructions — ADEGI

ADEGI is an elderly-care companion robot (university course project treated as a real product). It tracks and follows people, detects falls, gives medication reminders by asking, holds conversations, returns to a charging dock, and reports to a family app.

## Platform
- Main board: STM32MP257F-DK.
  - Cortex-A35 + NPU: Linux (Yocto image), vision inference.
  - Cortex-M33: Zephyr RTOS, real-time motor control.
- Sensor node: NXP FRDM-MCXN947, connected over I3C.
- Optional accelerator: Jetson Nano 2GB (CUDA) via sockets. The robot must keep working without it — always implement a fallback path.
- Drive: 2 side wheels + 1 small rear wheel, flat hard floors only.

## Repo layout
- `app/` — Flutter family app (Android first).
- `vision/` — YOLO detection + pose fine-tuning, dataset scripts, int8 export for the NPU.
- `firmware/m33/` — Zephyr application.
- `sensor-node/` — MCXN947 firmware (I3C target).
- `jetson-bridge/` — socket server/client between MP257 and Jetson.
- `docs/` — team docs (Spanish).

## Coding conventions
- Code, identifiers and comments in English.
- Dart: follow `flutter_lints`; state management kept simple.
- C (Zephyr/MCU): Zephyr coding style, no dynamic allocation in real-time paths.
- Python: type hints, `pathlib`, scripts runnable from the CLI with `argparse`.
- Inter-component messages: JSON over sockets/WebSockets unless real-time constraints require binary; document every message type in `docs/protocol.md`.
- Handle disconnections and timeouts explicitly; components must degrade gracefully.
- Prefer small, explained changes; the main developer is learning YOLO, Yocto and Zephyr.
