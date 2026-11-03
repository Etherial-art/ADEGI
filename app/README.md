# app/ — App familiar (Flutter)

App para que la familia consulte el estado de ADEGI y reciba alertas (caídas, recordatorios de medicamento no confirmados, batería baja).

- **Stack:** Flutter + Android Studio. Android primero.
- **Responsable:** David.
- **Estilo:** `flutter_lints`, manejo de estado simple.
- **Comunicación:** WebSocket con el robot usando los mensajes de [`docs/protocol.md`](../docs/protocol.md). La app debe mostrar claramente cuando el robot está desconectado en vez de mostrar datos viejos como si fueran actuales.

Aquí irá el proyecto creado con `flutter create` (pendiente).
