# Visión de ADEGI — Investigación y decisiones

> Fuente: investigación preliminar (Gemini, nov 2026) revisada por el equipo.
> Todo lo marcado **[VERIFICAR]** debe confirmarse contra documentación oficial antes de implementarlo o citarlo.

## 1. Objetivo
El sistema de visión debe:
1. **Detectar** personas y objetos del hogar relevantes: silla, sillón, cama, mesa, bastón, andadera.
2. **Estimar postura** con keypoints y clasificar a la persona como: `standing`, `sitting`, `lying_bed` o `fallen`.

Despliegue: **STM32MP257F-DK** (Cortex-A35 + NPU VeriSilicon, OpenSTLinux/Yocto), modelos cuantizados **int8**.
Requisito de la materia: CNN propia = modelo preentrenado con fine-tuning.

## 2. Arquitectura elegida: dos modelos en cascada (enfoque b)

| Componente | Modelo | Entrenamiento | Dónde corre |
|---|---|---|---|
| Detector de objetos | YOLOv8n (detección, 7 clases) | **Fine-tuning propio** (cumple el requisito) | NPU |
| Pose | YOLOv8n-pose (17 keypoints COCO) | Preentrenado del stm32ai-modelzoo; fine-tuning con caídas en fase 2 (opcional) | NPU |
| Clasificador de postura | MLP 36→64→32→3 | Propio | Cortex-A35, solo NumPy |
| Reglas de contexto | IoP + keypoints + altura | — | Cortex-A35 |

**Por qué no un solo YOLO-pose multiclase:** el cabezal de pose exige 17 keypoints por cada objeto (habría que rellenar camas y sillas con ceros), no existe un dataset público con muebles y keypoints a la vez, y la pérdida conjunta degrada la detección de objetos rígidos.

**Por qué YOLOv8n y no YOLO11n:** YOLO11n incluye bloques de atención (C2PSA: MatMul/Softmax) que pueden no mapearse completos a la NPU y forzar particiones del grafo. YOLOv8n es puramente convolucional (Conv + BN + SiLU), con cuantización int8 limpia y soporte oficial en el modelzoo de ST. **[VERIFICAR con benchmark en la placa]**

### Frame interleaving
La persona y los muebles no cambian a 50 Hz:
- **Pose:** cada frame.
- **Detector:** cada N frames (3–5), actualizando un mapa de muebles en memoria.
- Meta: ≥ 15–20 FPS efectivos con margen para el resto del sistema.

### Backends intercambiables
La misma lógica debe poder correr con:
- `stai_mpu` en la placa (NPU),
- Ultralytics en PC (desarrollo),
- Jetson Nano vía `jetson-bridge/` (opcional; **el robot no debe depender de ella**).

## 3. Cuantización — punto crítico
- La NPU del STM32MP25 rinde mucho mejor con cuantización **per-tensor** que con **per-channel**. Referencia del modelzoo para YOLOv8n-pose a 256×256: ~17.6 ms per-tensor vs ~103 ms per-channel. **[VERIFICAR cifras en el model card de ST]**
- Ultralytics exporta per-channel por defecto → usar los scripts de **stm32ai-modelzoo-services** para cuantizar per-tensor, o partir de los `.tflite` ya publicados por ST.
- Formato preferido: **TFLite int8** (cuantización estática post-entrenamiento con imágenes de calibración reales).
- Resolución de trabajo: **256×256** (la del benchmark de ST); 320×320 como alternativa.
- El flag `quantize=8` para exportar ONNX int8 con Ultralytics **[VERIFICAR — puede no existir]**. No depender de él.
- Opcional: precompilar a `.nb` con ST Edge AI Core (`stedgeai`) para evitar compilar al arrancar. **[VERIFICAR comando y target]**

## 4. Clases y datos

### Clases del detector
| ID | Clase | ¿En COCO? | ID COCO |
|---|---|---|---|
| 0 | person | Sí | 0 |
| 1 | chair | Sí | 56 |
| 2 | couch | Sí | 57 |
| 3 | bed | Sí | 59 |
| 4 | dining table | Sí | 60 |
| 5 | cane | No | — |
| 6 | walker | No | — |

### Cómo armar el dataset sin olvido catastrófico
1. Descargar datasets de bastón/andadera ya etiquetados (Roboflow Universe, búsqueda "walker cane"; Open Images V7 vía FiftyOne). **[VERIFICAR licencias y tamaños]**
2. Auto-etiquetar en esas imágenes las clases COCO presentes con `yolov8x.pt` filtrando `classes=[0, 56, 57, 59, 60]`.
3. Fusionar etiquetas y remapear IDs al esquema de 7 clases.
4. Añadir un subconjunto de COCO con camas, sillas, etc., para balancear.
5. Revisar una muestra a mano (CVAT o Roboflow).

### Datasets de caídas candidatos **[VERIFICAR todo: licencia, conteo, clases]**
| Dataset | Licencia reportada | Uso |
|---|---|---|
| CAUCAFall (Mendeley) | CC BY 4.0 | Caídas en entorno doméstico; cajas YOLO |
| Stand-Sit-Fall (Roboflow) | CC BY 4.0 | 3 clases: fall, sit, stand |
| Real Fall Detect (Roboflow) | CC BY 4.0 | 3 clases |
| UR Fall Detection | CC BY-NC-SA 4.0 | Solo uso académico no comercial |
| Le2i | Académico | fall / non-fall |

> ADEGI se plantea como producto: preferir licencias que permitan uso comercial y documentar la licencia de cada dato usado.

## 5. Formato de etiquetas de pose (YOLO-pose)
Una línea por persona, 56 valores normalizados [0, 1]:
```
<class> <xc> <yc> <w> <h> <x1> <y1> <v1> ... <x17> <y17> <v17>
```
- Visibilidad `v`: 0 = no etiquetado, 1 = ocluido, 2 = visible.
- Orden COCO: 0 nariz, 1–2 ojos, 3–4 orejas, 5–6 hombros, 7–8 codos, 9–10 muñecas, 11–12 caderas, 13–14 rodillas, 15–16 tobillos (izq, der).

`pose_data.yaml`:
```yaml
path: /content/fall_pose_dataset
train: images/train
val: images/val
kpt_shape: [17, 3]
flip_idx: [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]
names:
  0: person
```
Para generar keypoints sobre datasets que solo tienen cajas: inferencia con un modelo de pose grande (p. ej. `yolo11x-pose.pt`, `save_txt=True`) + revisión manual.

## 6. Clasificador de postura (MLP)
**Features (36):**
- 34: keypoints normalizados dentro de la caja de la persona (`(x - xmin)/w`, `(y - ymin)/h`); si la confianza es < 0.25 → 0.
- 1: relación de aspecto acotada `min(w/h, 3)/3`.
- 1: caída vertical del fémur `y_rodilla - y_cadera` (normalizada).

**Por qué normalizar:** con píxeles crudos la red aprendería *dónde* está la persona en la habitación, no *cómo* está.

**Modelo:** 36 → 64 → 32 → 3 (ReLU, dropout 0.2), ~4.5 k parámetros. Salida: `standing`, `sitting`, `horizontal`.
**Despliegue:** exportar pesos a `.npz`; inferencia en el A35 solo con NumPy (sin PyTorch en la placa).
**Datos:** keypoints extraídos de datasets de caídas/ADL etiquetados por postura.

## 7. Reglas de contexto: `lying_bed` vs `fallen`
Se aplican cuando la MLP devuelve `horizontal` (confirmable con ángulo de torso < 35° entre punto medio de hombros y de caderas).

**IoP (Intersection over Person)** en lugar de IoU, porque la cama es mucho más grande que la persona:
```
IoP = área(persona ∩ cama) / área(persona)
```

**`lying_bed`** si se cumplen todas:
- IoP ≥ 0.55 con `bed` o `couch`,
- ≥ 2 keypoints del tronco (nariz, hombros, caderas; conf > 0.3) dentro de la caja de la cama,
- `y_cadera < y_max_cama − 0.15·H_cama` (la cadera queda sobre el colchón, no en su base).

**`fallen`**: cualquier postura horizontal que no cumpla lo anterior. Señal adicional: bastón/andadera suelto lejos de la persona.

**Otros estados:**
- `standing` + bastón/andadera traslapado → "caminando con ayuda".
- `sitting` confirmado si IoP con chair/couch/bed > 0.3.

> Umbrales iniciales; calibrar con datos reales desde la altura de cámara del robot (~30–50 cm). Agregar filtro temporal (p. ej. `fallen` sostenido ≥ N segundos) antes de disparar la alerta.

## 8. Salida hacia el resto del sistema
La visión publica eventos `person_state` (definidos en `docs/protocol.md`):
- `state`: standing | sitting | lying_bed | fallen
- posición de la persona en imagen (y estimada respecto al robot cuando haya calibración)
- confianza y timestamp

Consumidores: máquina de estados (M33/comportamiento) y app familiar.

## 9. Despliegue en OpenSTLinux (como usuario, no integrador)
- OpenSTLinux = distribución de ST construida con Yocto. Para correr modelos **no hace falta compilar Yocto**.
- Runtime de IA mediante el paquete **X-LINUX-AI** (instalable en la placa con `apt`/la herramienta de ST). **[VERIFICAR nombres de paquetes en la ST wiki]**
- **No** instalar `onnxruntime`/`tflite-runtime` genéricos con pip: correrían en CPU e ignorarían la NPU. Usar la API **STAI MPU** de Python o el delegado de NPU del sistema.
- Medir latencia real con la herramienta de benchmark de ST antes de integrar. **[VERIFICAR nombre del comando]**
- Cámara: GStreamer/V4L2 (`v4l2src`), escalando por hardware a la resolución del modelo.

## 10. Plan de trabajo
1. [ ] Verificar los puntos **[VERIFICAR]** (ST wiki, modelzoo, docs de Ultralytics).
2. [ ] Benchmark en la placa con los `.tflite` oficiales de ST (detección y pose).
3. [ ] Armar dataset de 7 clases y hacer fine-tuning del detector en Colab.
4. [ ] Cuantizar per-tensor y validar mAP antes/después de cuantizar.
5. [ ] Extraer keypoints y entrenar la MLP de postura.
6. [ ] Implementar reglas de contexto con pruebas unitarias.
7. [ ] Loop principal con frame interleaving y backends intercambiables.
8. [ ] Integrar con `docs/protocol.md` y probar con la app.
9. [ ] Fase 2 (opcional): fine-tuning de YOLOv8n-pose con caídas.

## Referencias a revisar
- STMicroelectronics — stm32ai-modelzoo (GitHub) y model cards en Hugging Face (YOLOv8n, YOLOv8n-pose).
- ST Wiki — X-LINUX-AI, STAI MPU Python API, benchmark en STM32MPU.
- Ultralytics Docs — Export, Pose datasets, coco.yaml.
- Eraso et al. (2022), CAUCAFall, Mendeley Data, doi:10.17632/7w7fccy7ky.4.
- Kwolek & Kepski (2014), UR Fall Detection Dataset.
