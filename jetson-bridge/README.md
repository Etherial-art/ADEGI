# jetson-bridge/ — Puente MP257 ↔ Jetson Nano

Servidor (en la Jetson) y cliente (en el MP257) por sockets TCP para usar la Jetson Nano 2GB como **acelerador opcional** (inferencia con CUDA).

- **Regla principal:** el robot **no depende** de la Jetson. Si no está, no responde o excede el timeout, el cliente regresa al camino local (NPU del MP257) sin interrumpir el comportamiento.
- **Protocolo:** ver la sección *Jetson bridge* en [`docs/protocol.md`](../docs/protocol.md).
- Python con type hints, `pathlib` y `argparse`.

Estructura prevista: `server/` (Jetson), `client/` (MP257), `tests/`.
