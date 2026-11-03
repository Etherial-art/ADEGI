# vision/ — Visión con IA

Detección, seguimiento e identificación de personas y detección de caídas (persona en el piso).

- **Modelo:** YOLO (detección + pose), fine-tuning de un modelo preentrenado (CNN, requisito de la materia).
- **Despliegue:** cuantización int8 y exportación para la NPU del STM32MP257 (Cortex-A35, Linux/Yocto). Opcionalmente se descarga inferencia a la Jetson vía [`jetson-bridge/`](../jetson-bridge/), pero **siempre debe existir el camino en la NPU**.
- **Responsable:** David.

Estructura prevista:
- `datasets/` — scripts para descargar/convertir/etiquetar datos (los datos en sí **no** se suben a git).
- `train/` — scripts de fine-tuning.
- `export/` — cuantización int8 y exportación al formato de la NPU.
- `runtime/` — servicio de inferencia en el robot que publica mensajes `vision.*` (ver [`docs/protocol.md`](../docs/protocol.md)).

Python con type hints, `pathlib` y `argparse`.
