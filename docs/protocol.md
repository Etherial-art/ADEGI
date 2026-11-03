# Protocolos entre componentes

> Convención del proyecto: mensajes JSON simples, cada tipo documentado aquí.
> Este archivo se creó junto con el módulo de visión; agrega aquí los mensajes de los demás módulos.

## `person_state` (visión → comportamiento / app)

Un evento por frame procesado (JSON lines por stdout en `python -m adegi_vision`; el transporte final — socket/WebSocket — se decide al integrar).

```json
{"type":"person_state","ts":1730000000.12,"present":true,
 "state":"standing","confidence":0.83,"bbox":[100.0,100.0,200.0,400.0],
 "with_aid":false,"aid_far":false,"fall_alert":false}
```

| Campo | Tipo | Significado |
|---|---|---|
| `ts` | float | Epoch en segundos |
| `present` | bool | Hay una persona visible. Si es `false` solo vienen `ts` y `fall_alert` |
| `state` | str | `standing` \| `sitting` \| `lying_bed` \| `fallen`. Si un frame es inconcluso se repite el último estado concluyente |
| `confidence` | float | confianza de pose × probabilidad del MLP |
| `bbox` | [x1,y1,x2,y2] | píxeles del frame original |
| `with_aid` | bool | de pie con bastón/andadera traslapado ("caminando con ayuda") |
| `aid_far` | bool | bastón/andadera lejos de una persona caída (evidencia extra) |
| `fall_alert` | bool | **Alerta de caída**: `fallen` sostenido ≥ `fall_hold_s` (3 s por defecto). Este es el campo que debe disparar el aviso a la familia, no `state` |

`fall_alert` se mantiene activo si la persona sale de cuadro; solo se limpia cuando se la ve sin estar caída por ≥ 1 s.

## Puente Jetson (`vision` ↔ `jetson-bridge`)

TCP, una petición/respuesta a la vez. Si falla o excede el timeout, el cliente usa el backend local (la Jetson es opcional).

Petición: línea JSON + `\n` + bytes JPEG.
```json
{"type":"infer","task":"detect","seq":42,"jpeg_len":31244}
```
`task` ∈ `detect` | `pose`.

Respuesta: una línea JSON.
```json
{"type":"result","task":"detect","seq":42,"items":[{"cls":3,"conf":0.81,"box":[10,20,300,260]}]}
{"type":"result","task":"pose","seq":43,"items":[{"conf":0.9,"box":[10,20,100,300],"keypoints":[[x,y,c],"... 17 en total"]}]}
{"type":"error","message":"..."}
```
`cls` usa los ids de 7 clases (`person=0, chair=1, couch=2, bed=3, dining table=4, cane=5, walker=6`). `keypoints` en orden COCO, píxeles del frame original.

> El **servidor** de este protocolo (lado Jetson) aún no existe en `jetson-bridge/`; el cliente está probado contra un servidor falso en `vision/tests/test_pipeline_and_jetson.py`, que sirve como especificación ejecutable.
