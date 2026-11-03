# app/ — App familiar (Flutter)

App para que la familia consulte el estado de ADEGI y reciba alertas (caídas, recordatorios de medicamento no confirmados, batería baja).

- **Stack:** Flutter + Android Studio. Android primero.
- **Responsable:** David.
- **Estilo:** `flutter_lints`, manejo de estado simple (`ChangeNotifier`, sin paquetes extra).
- **Comunicación:** WebSocket con el robot usando los mensajes de [`docs/protocol.md`](../docs/protocol.md). La app muestra claramente cuando el robot está desconectado en vez de mostrar datos viejos como si fueran actuales.

## Qué hace

| Pantalla | Contenido |
|---|---|
| **Estado** | Conexión (Conectado / Sin señal / Reconectando / Desconectado), batería y si está en la base, modo (`idle`, `follow`…), última vez que vio a una persona. Si no hay conexión viva, los datos se atenúan y se indica "Último dato recibido hace X". |
| **Alertas** | Una caída (`alert.fall`) muestra un banner rojo en todas las pestañas, vibra y suena. "Reconocer" envía `alert.ack`; el robot deja de reenviarla. No se puede reconocer sin conexión (la alerta sigue abierta en vez de fingir que se atendió). |
| **Historial** | Caídas, medicinas, errores del sistema, batería baja y cortes de conexión. Se guarda en el teléfono (últimos 200) y sobrevive a reiniciar la app. |
| **Medicinas** | Recordatorios con su resultado (`pending` / `confirmed` / `declined` / `no_response`). Aviso si hay alguno sin confirmar. |

Ajustes (⚙): dirección del WebSocket del robot e identificador del familiar (se manda como `by` en `alert.ack`).

## Estructura

```
lib/
  protocol/envelope.dart      sobre JSON común (§2); ignora lo que no entiende
  services/robot_link.dart    WebSocket + reconexión automática (backoff 1→15 s)
  services/storage.dart       ajustes, historial y "visto por última vez" (shared_preferences)
  state/app_controller.dart   estado único de la app; interpreta cada mensaje
  models/, ui/                modelos y pantallas
tools/
  mock_robot.py               robot simulado (servidor WebSocket en Python)
  test_mock_robot.py          pruebas del simulador
test/                         pruebas de Dart (protocolo, controlador, enlace real, UI)
```

## Requisitos

- Flutter estable (probado con 3.47.x) y Android Studio con un emulador o un teléfono Android.
- Python 3.10+ para el robot simulado.

## Cómo correrla

**1. Levanta el robot simulado** (en una terminal):

```bash
cd app/tools
pip install -r requirements.txt
python mock_robot.py --demo
```

`--demo` ejecuta un guion (sigue a la persona, recordatorio de medicina, caída a los ~25 s, batería baja a los ~60 s). Sin `--demo` queda interactivo: escribe `fall`, `med`, `med-miss`, `mode follow`, `battery 15`, `person off`, `error`, `help`. Las alertas sin reconocer se reenvían cada 30 s (`--resend-s 5` para probar más rápido) y quedan en cola si la app no está conectada.

**2. Corre la app:**

```bash
cd app
flutter pub get
flutter run
```

- **Emulador Android:** funciona tal cual; la dirección por defecto `ws://10.0.2.2:8765/app` apunta a tu computadora.
- **Teléfono físico:** en ⚙ pon `ws://<IP-de-tu-compu>:8765/app` (misma red WiFi). Para el robot real: `ws://<ip-robot>:8765/app`.

**Para probar el estado desconectado:** detén el simulador (Ctrl+C). La app pasa a "Desconectado" y atenúa los datos; al volver a levantarlo, se reconecta sola y recibe las alertas pendientes.

## Pruebas

```bash
cd app && flutter analyze && flutter test
cd app/tools && python -m unittest test_mock_robot
```

## Limitaciones conocidas

- **Sin notificaciones push:** las alertas llegan en tiempo real solo con la app abierta y conectada (el WebSocket se corta en segundo plano). Es el pendiente "alerta fuera de la red" de `docs/protocol.md` §7; requiere servicio push/backend.
- **Tráfico sin cifrar y sin autenticación:** `ws://` en red local (el manifest habilita `usesCleartextTraffic`). Pendiente de §7 (autenticación del WebSocket).
- **Solo lectura de modo:** la app no envía `behavior.set_mode`, solo muestra el modo. El simulador sí lo soporta.
- Solo Android; no se generaron los proyectos iOS/web/escritorio.
