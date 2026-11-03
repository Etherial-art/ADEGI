# jetson-bridge

Cliente (MP257) y servidor (Jetson Nano) por sockets TCP. El MP257 envía frames JPEG y la Jetson responde detecciones en JSON. **El robot no depende de la Jetson**: si no responde, `BridgeClient.detect()` infiere con el detector local (NPU). Protocolo: [`docs/protocol.md`](../docs/protocol.md).

Solo biblioteca estándar de Python 3.10+ (nada que instalar en Yocto ni en la Jetson).

| Archivo | Rol |
|---|---|
| `protocol.py` | Framing (longitud + JSON + bytes) |
| `server.py` | Lado Jetson (`python3 server.py --port 5555`) |
| `client.py` | Lado MP257: heartbeat, timeout, reconexión, fallback |
| `detectors.py` | Interfaz `Detector` + `SimulatedDetector` |
| `demo.py` | Ambos lados en una máquina; tira y revive la "Jetson" |
| `tests/` | `unittest`, ambos lados simulados en localhost |

## Probar

```bash
cd jetson-bridge
python3 -m unittest discover -s tests -v   # 17 pruebas, ~2 s
python3 demo.py                            # ver el fallback en vivo
```

## Uso en el MP257

```python
client = BridgeClient("192.168.1.50", 5555, local_detector=npu_detector)
client.start()
result = client.detect(jpeg_bytes, width, height)  # siempre devuelve algo
result.source  # "jetson" | "local"
```

Para integrar YOLO real, implementar `Detector` (`name` + `detect(jpeg, w, h)`) para la NPU (cliente) y para CUDA (servidor, en lugar de `SimulatedDetector` en `server.py`).

## Limitación conocida

El servidor atiende cada conexión secuencialmente: una inferencia lenta retrasa también los `pong`. Es aceptable (la Jetson saturada *debe* degradarse y el cliente la reinicia), pero si se quiere heartbeat independiente de la inferencia, mover `detect()` a un hilo trabajador.
