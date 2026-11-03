# Protocolo de comunicación entre componentes

> **Estado:** borrador v0 (propuesta inicial, por discutir con el equipo).
> Si agregas o cambias un mensaje, actualiza este documento en el mismo PR.

## 1. Mapa de componentes y transportes

```
                 WebSocket (JSON)
   App Flutter  <---------------->  ┌──────────────── STM32MP257 ────────────────┐
                                    │  Cortex-A35 (Linux/Yocto)                  │
                                    │   ├─ vision      (YOLO en NPU)             │
   Jetson Nano  <---- TCP --------> │   ├─ behavior    (máquinas de estado)      │
   (opcional)      (JSON + binario) │   ├─ conversation (LLM)                    │
                                    │   └─ gateway     (WebSocket hacia la app)  │
                                    │        │ RPMsg (JSON compacto)             │
                                    │  Cortex-M33 (Zephyr) — control de motores  │
                                    └────────┬───────────────────────────────────┘
                                             │ I3C (registros binarios)
                                    FRDM-MCXN947 — nodo de sensores
```

| Enlace | Transporte | Formato | Por qué |
|---|---|---|---|
| Procesos dentro del A35 | WebSocket local (`ws://127.0.0.1:8765`) | JSON | Simple, depurable con cualquier cliente WebSocket, desacopla procesos (Python, Dart, C). |
| A35 ↔ App | WebSocket (`ws://<ip-robot>:8765/app`) | JSON | Flutter tiene soporte nativo; misma forma de mensajes que el bus interno. |
| A35 ↔ M33 | RPMsg (OpenAMP) | JSON compacto (≤ 256 B por mensaje) | RPMsg es el mecanismo estándar entre núcleos del MP2. Los mensajes son pequeños y a ~20 Hz; si el JSON resulta lento en el M33 se migra a binario (ver §6). |
| A35 ↔ MCXN947 | I3C | Mapa de registros binario | Bus de bajo nivel; JSON no tiene sentido aquí. |
| A35 ↔ Jetson | TCP (`:9000`) | Encabezado JSON + payload binario (JPEG) | Las imágenes en JSON (base64) inflan ~33 % el tamaño. |

## 2. Sobre (envelope) común para mensajes JSON

Todo mensaje JSON tiene esta forma:

```json
{
  "v": 1,
  "type": "vision.persons",
  "src": "vision",
  "seq": 1042,
  "ts": 1793836800123,
  "data": { }
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `v` | int | Versión del protocolo. Se incrementa ante cambios incompatibles. |
| `type` | string | Tipo de mensaje, formato `dominio.nombre`. |
| `src` | string | Componente que lo emite: `vision`, `behavior`, `conversation`, `gateway`, `m33`, `jetson`, `app`. |
| `seq` | int | Contador por emisor; sirve para detectar mensajes perdidos o duplicados. |
| `ts` | int | Marca de tiempo Unix en milisegundos (reloj del emisor). |
| `data` | object | Contenido específico del tipo. |
| `reply_to` | int (opcional) | `seq` del mensaje al que responde (para pares petición/respuesta). |

**Reglas:**
- Unidades SI: metros, radianes, segundos (salvo `ts` en ms). Porcentajes de 0 a 100.
- Campos en `snake_case`.
- Los receptores **ignoran campos desconocidos** (permite agregar campos sin romper a nadie).
- Mensajes de tipo desconocido se ignoran y se registran en el log, no rompen el proceso.

## 3. Mensajes

### 3.1 Sistema

#### `sys.heartbeat` — todos → bus, cada 1 s
```json
{ "status": "ok", "uptime_s": 3600 }
```
`status`: `ok` | `degraded` | `error`. Si no llega heartbeat de un componente en **3 s**, se considera caído y el resto degrada (ver §5).

#### `sys.error`
```json
{ "code": "camera_unavailable", "message": "No frames for 2 s", "severity": "warning" }
```
`severity`: `info` | `warning` | `critical`.

### 3.2 Visión (`vision` → bus)

#### `vision.persons` — por cada frame procesado (~10–15 Hz)
```json
{
  "frame_id": 88213,
  "backend": "npu",
  "persons": [
    {
      "track_id": 3,
      "identity": "maria",
      "identity_conf": 0.81,
      "bbox": [0.31, 0.12, 0.22, 0.75],
      "conf": 0.93,
      "posture": "standing",
      "bearing_rad": -0.12,
      "distance_m": 1.8
    }
  ]
}
```
- `backend`: `npu` | `jetson` — permite saber qué camino se usó.
- `bbox`: `[x, y, w, h]` normalizados (0–1) respecto al frame.
- `identity`: `null` si no se reconoce.
- `posture`: `standing` | `sitting` | `lying` | `unknown`.
- `bearing_rad`: ángulo horizontal respecto al frente del robot (positivo = izquierda).
- `distance_m`: estimado; `null` si no hay estimación confiable.

#### `vision.fall_detected`
```json
{ "track_id": 3, "identity": "maria", "conf": 0.88, "lying_duration_s": 5.0 }
```
Se emite cuando una persona permanece en `lying` más de un umbral (evita falsos positivos por alguien que se agacha).

### 3.3 Comportamiento (`behavior`)

#### `behavior.state` — al cambiar y cada 5 s
```json
{ "mode": "follow", "target_track_id": 3, "battery_pct": 72, "docked": false }
```
`mode`: `idle` | `roam` | `follow` | `docking` | `charging` | `alert` | `error`.

#### `behavior.set_mode` — app/conversation → behavior
```json
{ "mode": "idle" }
```
Respuesta: `behavior.ack` con `reply_to` y `{ "ok": true }` o `{ "ok": false, "reason": "..." }`.

### 3.4 Alertas y recordatorios (`behavior` → `gateway` → app)

#### `alert.fall`
```json
{
  "alert_id": "a-20261103-0001",
  "identity": "maria",
  "conf": 0.88,
  "snapshot_available": false,
  "acknowledged": false
}
```

#### `alert.ack` — app → robot
```json
{ "alert_id": "a-20261103-0001", "by": "familiar_1" }
```
Mientras una alerta no se reconozca, el robot la reenvía cada 30 s a las apps conectadas.

#### `reminder.medication`
```json
{
  "reminder_id": "r-0007",
  "medication": "Losartán 50 mg",
  "scheduled_at": 1793840400000,
  "result": "confirmed"
}
```
`result`: `pending` | `confirmed` | `declined` | `no_response`. La confirmación es **verbal** (la persona responde a la pregunta), no hay verificación visual.

### 3.5 Control de movimiento (A35 ↔ M33, por RPMsg)

Mensajes cortos para caber en un buffer RPMsg (≤ 256 B). `src`/`ts` pueden omitirse en este enlace para ahorrar espacio; `seq` es obligatorio.

#### `motion.cmd` — A35 → M33, ~20 Hz
```json
{"v":1,"type":"motion.cmd","seq":51,"data":{"lin":0.25,"ang":-0.10}}
```
- `lin`: velocidad lineal deseada (m/s). `ang`: velocidad angular (rad/s).
- El M33 limita los valores a sus máximos configurados.
- **Watchdog:** si el M33 no recibe `motion.cmd` en **300 ms**, frena los motores.

#### `motion.stop` — A35 → M33
```json
{"v":1,"type":"motion.stop","seq":52,"data":{"reason":"fall_alert"}}
```

#### `motion.odom` — M33 → A35, ~20 Hz
```json
{"v":1,"type":"motion.odom","seq":9001,"data":{"x":1.23,"y":-0.40,"th":0.52,"lin":0.24,"ang":-0.09,"fault":0}}
```
`fault`: bitmask (bit0 = sobrecorriente, bit1 = watchdog disparado, bit2 = paro de emergencia).

### 3.6 Conversación (`conversation`)

#### `conversation.utterance`
```json
{ "speaker": "user", "identity": "maria", "text": "¿Qué día es hoy?" }
```
`speaker`: `user` | `robot`. Sirve para registro y para que `behavior` reaccione a intenciones (p. ej. "sígueme").

## 4. Puente Jetson (TCP `:9000`)

Cada mensaje es un **frame** con prefijo de longitud (big-endian):

```
[uint32 header_len][header JSON (UTF-8)][uint32 payload_len][payload binario]
```

`payload_len` = 0 si no hay payload.

#### `jetson.infer_request` — MP257 → Jetson
Header: `{"v":1,"type":"jetson.infer_request","seq":120,"ts":...,"data":{"frame_id":88213,"model":"yolo-pose","format":"jpeg","width":640,"height":480}}`
Payload: imagen JPEG.

#### `jetson.infer_result` — Jetson → MP257
Header con `reply_to` y `data.persons` en el mismo formato que `vision.persons`. Sin payload.

**Fallback:** si no hay respuesta en **150 ms**, el MP257 procesa ese frame en la NPU. Tras 3 timeouts seguidos o conexión caída, deja de enviar a la Jetson y reintenta la conexión cada 10 s.

## 5. Degradación ante fallas

| Falla | Detección | Reacción |
|---|---|---|
| Jetson caída/lenta | Timeout 150 ms / socket cerrado | Inferencia en NPU; `vision.persons.backend = "npu"`. |
| Visión caída | Sin heartbeat 3 s | `behavior` pasa a `idle` y detiene movimiento. |
| M33 no responde | Sin `motion.odom` 500 ms | `behavior` pasa a `error`, notifica a la app. |
| A35 deja de mandar comandos | Watchdog M33 300 ms | M33 frena motores. |
| Nodo de sensores (I3C) | Error de bus / dato viejo | Movimiento detenido o modo seguro. |
| App desconectada | WebSocket cerrado | Las alertas quedan en cola y se reenvían al reconectar. |

## 6. Nodo de sensores (I3C) — por definir

El MCXN947 expone un mapa de registros binario (little-endian). Propuesta inicial:

| Dirección | Tamaño | Contenido |
|---|---|---|
| `0x00` | 1 B | `WHO_AM_I` (valor fijo para validar el enlace) |
| `0x01` | 1 B | Versión del mapa de registros |
| `0x02` | 1 B | Estado / flags de error |
| `0x03` | 2 B | Contador de muestra (detecta datos viejos) |
| `0x10…` | — | Datos de sensores (por definir según sensores elegidos) |

## 7. Pendientes

- [ ] Confirmar si el JSON sobre RPMsg cabe en los tiempos del M33 o se migra a binario (CBOR o structs).
- [ ] Definir cómo llega una alerta a la app cuando no está en la misma red (servicio push / backend en la nube).
- [ ] Autenticación del WebSocket de la app.
- [ ] Mapa de registros final del nodo de sensores.
