# sensor-node/ — Nodo de sensores (NXP FRDM-MCXN947)

Firmware del MCXN947, que lee sensores (distancia/obstáculos, IMU, batería, etc.) y los expone al STM32MP257 como **target I3C**.

- **Por qué un nodo aparte:** descarga al MP257 del muestreo de sensores y aísla fallas de hardware; I3C da más velocidad que I2C con el mismo par de cables.
- **Protocolo:** mapa de registros binario sobre I3C (no JSON: el bus es de bajo nivel). El mapa de registros se documenta en [`docs/protocol.md`](../docs/protocol.md).
- **Degradación:** si el nodo no responde, el robot debe detenerse o moverse en modo seguro, nunca usar lecturas viejas como válidas.

Aquí irá el proyecto del firmware (MCUXpresso SDK o Zephyr, por definir).
