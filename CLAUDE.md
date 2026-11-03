# ADEGI — Contexto del proyecto

## Qué es
ADEGI es un robot asistente cognitivo para el cuidado de adultos mayores, proyecto de la materia *Sistemas Embebidos Avanzados con IA* (Tec de Monterrey, CEM, otoño 2026). El nombre es un acrónimo de las iniciales del equipo. Se trata como **producto real** (BOM, CBOM, análisis de riesgos), no como proyecto escolar.

Funciones del prototipo 1:
- Detectar, seguir e identificar personas (seguir = compañía; modos roam / follow / idle).
- Detectar si una persona está en el piso (caída) y alertar a la familia.
- Recordatorios de medicamento preguntándole a la persona (sin verificación visual).
- Conversación libre (LLM).
- Regreso autónomo a estación de carga.
- App para que la familia consulte el estado.

Fuera de alcance del prototipo 1: escaleras, escalones, umbrales, alfombra. Solo piso duro y plano.

## Forma
Cuerpo tipo cápsula/tortuga simétrico, cabeza plana con visor y dos pantallas como ojos. 3 ruedas: dos motrices laterales + una pequeña bajo una cola corta. Concepto de carcasa superior inflable (bomba + válvula) con frente/parte baja rígida.
Unidad secundaria futura: **MADEGI** (mini ADEGI) para la habitación.

## Hardware
- **STM32MP257F-DK** (placa principal):
  - Cortex-A35 + NPU → Linux (imagen Yocto), visión con IA.
  - Cortex-M33 + **Zephyr** → control en tiempo real (motores, estados de bajo nivel).
- **NXP FRDM-MCXN947** → nodo de sensores, comunicado por **I3C** con el MP257.
- **Jetson Nano 2GB** (prestada, CUDA) → integrada por **sockets** como acelerador opcional. **El robot NO debe depender de ella**: todo debe funcionar sin la Jetson (fallback en el MP257).
- No se usa Raspberry Pi.

## Software / módulos
| Módulo | Stack | Responsable |
|---|---|---|
| Visión | YOLO (detección + pose), fine-tuning de modelo preentrenado (CNN), cuantización int8 para la NPU | David |
| App familiar | Flutter + Android Studio | David |
| Conversación / LLM | — | Alexa |
| Comportamiento / máquinas de estado | — | Edu |
| Control | Zephyr en M33 | Isis |
| Diseño mecánico | SolidWorks | Gabriel (+ David) |

Requisito de la materia: red neuronal propia = modelo preentrenado con fine-tuning es válido, debe ser CNN. El profesor provee la parte de despliegue.

## Convenciones
- Código y comentarios en inglés; documentación para el equipo en español.
- Cada módulo en su carpeta (`app/`, `vision/`, `firmware/m33/`, `sensor-node/`, `jetson-bridge/`, `docs/`).
- Comunicación entre componentes con protocolos simples y documentados (mensajes JSON por socket/WebSocket salvo que el tiempo real exija binario).
- Todo componente debe degradar con gracia si otro falla (en especial la Jetson).

## Cómo trabajar conmigo
- Soy estudiante de robótica y estoy aprendiendo YOLO, Yocto y Zephyr: explica el **porqué** de cada decisión técnica, no solo el qué.
- Respuestas concisas, sin relleno.
- Antes de cambios grandes, propone un plan corto.
- Incluye instrucciones para correr/probar lo que generes.
