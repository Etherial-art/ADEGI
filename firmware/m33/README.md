# firmware/m33/ — Control en tiempo real (Zephyr)

Aplicación Zephyr que corre en el **Cortex-M33** del STM32MP257F-DK: control de motores (2 ruedas motrices laterales), odometría y estados de bajo nivel (paro de emergencia, watchdog).

- **Responsable:** Isis.
- **Por qué en el M33 y no en Linux:** el A35 corre Linux, que no garantiza tiempos de respuesta; el lazo de control de motores necesita periodos fijos, así que va en un RTOS.
- **Comunicación con el A35:** RPMsg/OpenAMP (memoria compartida entre núcleos). Ver [`docs/protocol.md`](../docs/protocol.md).
- **Seguridad:** si deja de recibir comandos del A35 dentro del timeout, detiene los motores.
- **Estilo:** Zephyr coding style, sin memoria dinámica en caminos de tiempo real.

Aquí irá la aplicación Zephyr (`CMakeLists.txt`, `prj.conf`, `src/`, overlays de devicetree).
