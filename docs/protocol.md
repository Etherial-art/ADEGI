# Protocolo de mensajes

## jetson-bridge (MP257 ⇄ Jetson Nano, TCP)

**Versión:** 1 · **Puerto por defecto:** 5555 · MP257 = cliente, Jetson = servidor.

### Envelope

Cada mensaje en el stream TCP es:

```
header_len u32 BE | payload_len u32 BE | header (JSON UTF-8) | payload (bytes crudos)
```

TCP es un flujo de bytes sin fronteras de mensaje, por eso el prefijo de longitud. El header es JSON (legible, depurable); la imagen va como bytes crudos porque base64 dentro de JSON añadiría ~33 % de ancho de banda y CPU. Límites: header ≤ 64 KB, payload ≤ 4 MB; si el prefijo los excede, se descarta la conexión (protege de basura/ataques).

Todo header lleva `"type"`.

### Mensajes

| type | Dirección | Campos | Payload |
|---|---|---|---|
| `hello` | MP257 → Jetson | `version` | — |
| `hello_ack` | Jetson → MP257 | `version`, `model` | — |
| `ping` | MP257 → Jetson | `seq` | — |
| `pong` | Jetson → MP257 | `seq` | — |
| `frame` | MP257 → Jetson | `id`, `ts`, `width`, `height`, `encoding` (`"jpeg"`) | JPEG |
| `detections` | Jetson → MP257 | `id`, `model`, `latency_ms`, `detections[]`, `error?` | — |

Cada elemento de `detections[]`: `{"cls": "person", "conf": 0.87, "bbox": [x1, y1, x2, y2]}` (píxeles del frame enviado, origen arriba-izquierda). Si la Jetson falla al inferir, responde `detections: []` con `error`; el cliente lo trata como fallo y usa el fallback.

### Comportamiento (timeouts y fallback)

| Parámetro (default) | Qué hace |
|---|---|
| `request_timeout` (0.5 s) | Máximo de espera por un `detections`. Si vence → se infiere localmente. Una respuesta tardía se ignora (se identifica por `id`). |
| `heartbeat_interval` (1 s) | Periodo de `ping`. |
| `heartbeat_timeout` (3 s) | Si no llega **ningún** mensaje en este tiempo, el enlace se declara caído (detecta Jetson colgada con TCP aún abierto, algo que un EOF no avisa). |
| `max_consecutive_timeouts` (3) | N respuestas lentas seguidas → se reinicia el enlace (responde pings pero está saturada). |
| `reconnect_min/max` (0.5–5 s) | Reintento con backoff exponencial. |
| Servidor `idle_timeout` (10 s) | Cierra clientes que no envían nada (robot sin WiFi/energía). |

Con el enlace caído, `detect()` va directo al detector local sin intentar enviar (sin latencia extra). Al reconectar vuelve a usar la Jetson automáticamente.
