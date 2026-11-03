# vision/ — Visión de ADEGI (enfoque b: dos modelos en cascada)

Diseño y decisiones: [`vision-research.md`](../vision-research.md) (está en la raíz del repo, no en `docs/`). Mensajes: [`docs/protocol.md`](../docs/protocol.md).

```
frame ─┬─► pose (YOLOv8n-pose, CADA frame) ─► features(36) ─► MLP ─► standing/sitting/horizontal ─┐
       └─► detector (YOLOv8n 7 clases, cada N frames) ─► mapa de muebles ──────────────────────────┤
                                                                                                   ▼
                                                      reglas de contexto (IoP) ─► standing|sitting|lying_bed|fallen
                                                                                  └► filtro temporal ─► fall_alert
```

## Qué hay (y por qué)

| Pieza | Archivo | Por qué existe |
|---|---|---|
| Ids de clase, mapeo COCO | `adegi_vision/classes.py` | Una sola fuente de verdad; un id distinto entre etiquetas y backend arruina el entrenamiento sin avisar |
| Auto-etiquetado | `tools/autolabel.py` | Evita el **olvido catastrófico**: las imágenes de bastón/andadera no traen etiquetadas las sillas/camas/personas; yolov8x (`classes=[0,56,57,59,60]`) las rellena |
| Fusión + `data.yaml` | `tools/merge_dataset.py`, `dataset.py` | Remapea por **nombre** (cada dataset numera distinto), conserva splits, deja un manifiesto con la **licencia** de cada fuente |
| Entrenamiento detector | `notebooks/train_detector_colab.ipynb` | fine-tuning de `yolov8n.pt` a `imgsz=256` + export TFLite int8 |
| Backends | `backends/` | `stai_mpu` (placa), `ultralytics` (PC), `jetson` (opcional, con **fallback local**) detrás de la misma interfaz |
| Decodificación | `decode.py` | La NPU solo corre el núcleo convolucional; decodificar tensores → cajas/keypoints y NMS se hace en CPU, en NumPy, probado sin placa |
| Features | `features.py` | Keypoints normalizados **dentro de la caja** → el MLP aprende *cómo* está la persona, no *dónde* |
| MLP | `posture_mlp.py` | 36→64→32→3 (4 547 parámetros). Inferencia **y** entrenamiento en NumPy: nada de PyTorch en la placa |
| Reglas de contexto | `context_rules.py` | Acostado en cama y caído en el piso tienen la misma pose; solo el entorno los distingue. Usa **IoP** (no IoU) porque la cama es mucho más grande que la persona |
| Loop | `pipeline.py`, `__main__.py` | **Frame interleaving**: pose cada frame, detector cada N; los muebles se mueven poco, las personas sí |

## Cómo probar

```bash
cd vision
pip install numpy opencv-python-headless
python -m unittest discover tests        # 72 pruebas, ~1 s, sin modelos ni placa
```

Qué cubren: IoP y reglas `lying_bed` vs `fallen` (cama, sillón, cadera en la base de la cama, junto a la cama, torso erguido contradictorio, bastón lejos/cerca), filtro temporal (parpadeo no dispara ni oculta una caída), MLP (entrena con datos sintéticos, guarda/carga `.npz`), decodificación YOLO (letterbox, normalizado vs píxeles, NMS por clase, int8), `StaiMpuBackend` con una red falsa, cliente Jetson contra un servidor falso (éxito, sin servidor, timeout, back-off), fusión de datasets y `data.yaml`, intercalado del pipeline.

## Flujo completo

```bash
pip install ultralytics   # PC / Colab

# 1. Etiquetas COCO sobre las imágenes de bastón/andadera
python -m adegi_vision.tools.autolabel --images data/canewalker --out data/autolabels

# 2. Fusión → data.yaml + dataset_manifest.json (licencias)
python -m adegi_vision.tools.merge_dataset --out data/adegi_det --autolabels data/autolabels \
    --source canewalker data/canewalker "CC BY 4.0" --source coco_subset data/coco_sub "CC BY 4.0"

# 3. Entrenar y exportar: abre notebooks/train_detector_colab.ipynb en Colab (GPU)

# 4. Postura: carpetas data/posture/{standing,sitting,horizontal}/*.jpg
python -m adegi_vision.tools.extract_keypoints --root data/posture --pose-model yolov8n-pose.pt --out data/posture_features.npz
python -m adegi_vision.tools.train_posture --features data/posture_features.npz --out models/posture_mlp.npz

# 5. Loop (PC, webcam)
python -m adegi_vision --backend ultralytics --source 0 \
    --det-model runs/adegi_det256/weights/best.pt --pose-model yolov8n-pose.pt --posture-model models/posture_mlp.npz

# En la placa (rutas a los modelos ya cuantizados/compilados)
python -m adegi_vision --backend stai_mpu --source <cam> --det-model det.nb --pose-model pose.nb --posture-model posture_mlp.npz

# Con Jetson opcional; si no responde, usa --local-backend
python -m adegi_vision --backend jetson --local-backend stai_mpu --jetson-host 192.168.x.x ...
```

`models/`, `data/`, `*.pt`, `*.tflite`, `*.npz` están en `.gitignore` (pesos y datos grandes, con licencia propia). El MLP pesa ~18 KB: si quieres versionarlo, `git add -f`.

## Verificación contra documentación oficial

Se pidió confirmar cada flag de exportación/cuantización. **Acceso limitado en esta sesión**: `docs.ultralytics.com`, `wiki.st.com` y `huggingface.co` no resolvieron (dominios fuera de la red permitida), y mis rutas a `stm32ai-modelzoo` en GitHub dieron 404. Lo que sí pude leer:

### Confirmado
| Punto | Fuente | Notas |
|---|---|---|
| Ultralytics tiene el argumento `quantize` (`8`/`"int8"`, `16`/`"fp16"`, `"w8a16"`, `"w8a32"`); `int8` y `half` son **legados** que reenvían a `quantize=8/16` | `docs/en/modes/export.md` en `ultralytics/ultralytics` (rama `main`) | Esto **corrige** el «[VERIFICAR — puede no existir]» de `vision-research.md` §3: sí existe, pero en `main`. No sé desde qué versión; por eso el notebook prueba `quantize=8` y cae a `int8=True` |
| Calibración estática con `data=` (p. ej. `coco8.yaml`) | idem | `"w8a32"` es dinámico y no necesita datos |
| NPU del MP25: cuantización **8-bit per-tensor asimétrica** para mejor rendimiento; per-channel corre «principalmente en GPU» | ST wiki *ST Edge AI: Guide for MPU* | Leído como fragmento de resultado de búsqueda, no la página completa |
| El NPU solo ejecuta formato **NBG** (`.nb`), generado con `stedgeai generate --target stm32mp25` desde TFLite/ONNX cuantizado; el componente MP2 es solo Linux | idem | Otros flags de `stedgeai` (entrada, salida, rutas) **no** confirmados |
| Si el modelo trae post-proceso como operador custom, la conversión lo elimina; ST sugiere NBG para el núcleo y post-proceso en CPU | idem | Es lo que implementa `decode.py` |
| Existe un ejemplo Python de pose con YOLOv8n cuantizado vía API `STAI_MPU` para MP23/MP25, y el paquete `stai-mpu-pose-estimation-python` | página de X-LINUX-AI | Nombres de paquete confirmados solo como aparecen en el resultado de búsqueda |

### NO confirmado (verifícalo antes de depender de ello)
1. **Cifras 17.6 ms (per-tensor) vs 103 ms (per-channel)** para YOLOv8n-pose 256×256: no pude abrir el model card. La *dirección* (per-tensor mejor) sí está respaldada; los números no. Mide en tu placa.
2. **Si el `.tflite` int8 de Ultralytics sale per-channel.** La doc de Ultralytics no menciona per-tensor/per-channel. El notebook incluye una celda que cuenta tensores con escalas por canal en el `.tflite` resultante: úsala.
3. **Cómo obtener per-tensor.** `vision-research.md` propone los scripts de `stm32ai-modelzoo-services`; no pude leer su interfaz (ni confirmar una opción de granularidad en su YAML de configuración). **Esta PR no implementa ese paso de cuantización**: el notebook deja el detector en `.tflite` int8 de Ultralytics y documenta el hueco. Para el modelo de pose, la idea es usar el `.tflite` ya cuantizado por ST (nombre y ruta exactos en el modelzoo: no confirmados).
4. **Formato exacto de salida de los `.tflite` de ST** (forma `(1,56,N)` vs `(1,N,56)`, coordenadas en píxeles o normalizadas, activaciones ya aplicadas). `decode.py` acepta ambas orientaciones y autodetecta píxeles/normalizado, pero es una suposición; si el modelo trae NMS integrado, hay que saltarse esa parte.
5. **Llamadas de `stai_mpu`** (`stai_mpu_network(model_path=…, use_hw_acceleration=…)`, `get_input_infos`, `set_input`, `run`, `get_output`, `get_qparams`): escritas de memoria. Están aisladas en la clase `_StaiNet` de `backends/stai_mpu_backend.py`; contrástalas con el ejemplo del paquete de pose de X-LINUX-AI.
6. Comando de benchmark de ST, nombres de paquetes `apt` de X-LINUX-AI, uso del delegado de NPU del sistema.
7. Que `YOLO("modelo.tflite").val()` funcione en tu versión (celda del notebook), y los nombres de archivo que escribe `export(format="tflite")`.
8. Llamadas a `fiftyone` para el subconjunto COCO (comentadas en el notebook).
9. `cv2.VideoCapture` con una tubería GStreamer requiere OpenCV compilado con GStreamer; no comprobado en la imagen de la placa.
10. **Licencias y tamaños** de todos los datasets (Roboflow, Open Images, CAUCAFall, etc.): no revisados. El manifiesto de `merge_dataset` te obliga a escribir la licencia de cada fuente, pero tú tienes que averiguarla.
11. YOLOv8n vs YOLO11n en la NPU (benchmark en placa pendiente, según `vision-research.md`).

## Qué NO se ha ejecutado

Probado aquí: toda la lógica NumPy (features, MLP, reglas, decodificación, pipeline, cliente Jetson, fusión de datasets). **No ejecutado** por falta de `ultralytics`, GPU, datos y placa: `autolabel`, `extract_keypoints`, `UltralyticsBackend`, el notebook (solo se validó la sintaxis de sus celdas), `StaiMpuBackend` con la API real de `stai_mpu`, y cualquier medición de FPS/mAP. Los umbrales de `RuleConfig` son iniciales: calibrarlos con video real desde la altura de la cámara del robot (~30–50 cm).

## Decisiones a revisar

- **Un solo debouncer para toda la escena** (se asume una persona al cuidado). Con visitas, una persona caída y otra de pie seguiría contando como caída (correcto), pero no hay seguimiento por persona.
- **Estado `unknown` interno**: si el MLP dice «horizontal» pero el torso está a ≥ 35° de la horizontal, el frame se descarta y se mantiene el último estado.
- Sin cadera visible, la regla de «cadera sobre la base de la cama» usa el centro de la caja de la persona.
- Si la persona sale de cuadro estando caída, `fall_alert` se mantiene activo hasta ver a alguien que no esté caído (preferimos una alerta de más a una de menos).
- Mapa de muebles: se reemplaza completo en cada ejecución del detector (sin histéresis). Un mueble no detectado en una pasada desaparece hasta la siguiente.
- `docs/vision-research.md` (mencionado en la tarea) vive en la raíz como `vision-research.md`; no lo moví.
