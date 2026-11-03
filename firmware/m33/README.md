# Firmware M33 (Zephyr) — ADEGI

Control en tiempo real del Cortex-M33 del STM32MP257F-DK: máquina de estados
de bajo nivel, 2 motores diferenciales por PWM, y enlace RPMsg/OpenAMP con el A35.
Responsable: Isis.

## Estado

Compila contra stubs por defecto. **Aún no está compilado contra Zephyr ni probado en
la placa** (el código se escribió sin toolchain; solo la lógica pura tiene tests en host).
Lo que falta para hardware real está marcado como `TODO(verify)` / en el `.overlay.example`.

## Arquitectura (y por qué)

```
A35 (Linux)  ──RPMsg "adegi-ctrl"──►  link ─► msgq ─► FSM ─► drive_mix ─► motor (PWM+DIR)
             ◄── STATUS cada 100 ms ──┘
```

- **A35 decide, M33 ejecuta y protege.** Visión/navegación (YOLO) corren en Linux y mandan
  velocidades; el M33 garantiza el comportamiento seguro aunque Linux se cuelgue.
- **Dead-man:** si en `roam/follow/return_to_dock` no llega `SET_VEL` en 500 ms, los motores
  se detienen. Es el equivalente a "degradar con gracia": un fallo del A35 no deja el robot
  corriendo.
- **FSM pura (`fsm.c`, `drive.c`, `protocol.c`) sin dependencias de Zephyr:** se prueba en host
  en milisegundos, sin placa. Las capas de hardware (`motor.c`, `link_*.c`) son delgadas.
- **Cola de eventos (`k_msgq`):** el callback de RPMsg solo decodifica y encola; un único hilo
  toca la FSM, así no hacen falta mutex.
- **Mezcla diferencial con escalado proporcional:** si una rueda saturaría, se escalan ambas
  igual para conservar el radio de giro (recortar solo una cambia la trayectoria).
- **Binario y no JSON** en este enlace: setpoints a ~50 Hz en el camino de control; CLAUDE.md
  permite binario cuando el tiempo real lo exige. El resto del sistema sigue en JSON.

## Estados

| Estado | Motores | Entra por | Sale por |
|---|---|---|---|
| `idle` | off | arranque, `SET_MODE 0`, alerta despejada | `SET_MODE` |
| `roam` | `SET_VEL` | `SET_MODE 1` | `SET_MODE`, batería baja, alerta |
| `follow` | `SET_VEL` | `SET_MODE 2` | ídem |
| `return_to_dock` | `SET_VEL` | `SET_MODE 3`, `BATTERY_LOW` | `DOCK_CONTACT 1` → `charging` |
| `charging` | off | contacto con la base | `SET_MODE`; contacto perdido |
| `alert` | off | `ALERT 1` desde cualquier estado | `ALERT 0` → `idle` |

Con batería baja, `roam`/`follow` se rechazan y se redirige a `return_to_dock`. En `alert` los
comandos de modo se ignoran hasta despejar la alerta (decisión de seguridad: una caída no se
"borra" con un comando de movimiento).

## Protocolo (little-endian, endpoint RPMsg `adegi-ctrl`)

| Dir | Tipo | Payload |
|---|---|---|
| A35→M33 | `0x01 SET_MODE` | `u8` 0 idle, 1 roam, 2 follow, 3 return_to_dock |
| A35→M33 | `0x02 SET_VEL` | `i16 v_mm_s`, `i16 w_mrad_s` (+ = antihorario) |
| A35→M33 | `0x03 DOCK_CONTACT` | `u8` 0/1 |
| A35→M33 | `0x04 ALERT` | `u8` 0/1 |
| A35→M33 | `0x05 BATTERY_LOW` | `u8` 0/1 |
| M33→A35 | `0x81 STATUS` | `u8 state`, `u8 flags` (b0 alert, b1 batt_low, b2 vel_stale), `i16 left_pm`, `i16 right_pm` |

Mensajes mal formados se descartan con un warning.

## Probar la lógica en host (sin Zephyr)

```bash
make -C firmware/m33/tests test
```

## Compilar con west

Requisitos: [Zephyr getting started](https://docs.zephyrproject.org/latest/develop/getting_started/index.html)
(dependencias del sistema, `west`, Zephyr SDK con `arm-zephyr-eabi`).

1. Crear el workspace (el manifiesto vive en este repo; `west` descarga Zephyr al lado):

```bash
python3 -m venv ~/adegi-ws/.venv && source ~/adegi-ws/.venv/bin/activate
pip install west
west init -m https://github.com/etherial-art/adegi --mf firmware/m33/west.yml ~/adegi-ws
cd ~/adegi-ws && west update
pip install -r zephyr/scripts/requirements.txt
west zephyr-export
```

   Si ya tienes el repo clonado: `west init -l --mf firmware/m33/west.yml <ruta>/ADEGI`.

2. Compilar en simulación (no requiere placa; usa los stubs y corre el guion de prueba):

```bash
west build -b native_sim adegi/firmware/m33 --pristine
./build/zephyr/zephyr.exe
```

3. Compilar para el M33 de la placa:

```bash
west build -b stm32mp257f_dk/stm32mp257xx/m33 adegi/firmware/m33 --pristine
```

   `TODO(verify)`: el nombre exacto del board target depende de la versión de Zephyr de
   `west.yml`; confírmalo con `west boards | grep mp257`. Si tu versión no lo incluye, sube
   `revision` en `west.yml`.

4. Con RPMsg real: copia `boards/*.overlay.example` a `boards/stm32mp257f_dk_stm32mp257xx_m33.overlay`,
   ajusta nodos/pines y compila con el fragmento:

```bash
west build -b stm32mp257f_dk/stm32mp257xx/m33 adegi/firmware/m33 --pristine -- -DEXTRA_CONF_FILE=rpmsg.conf
```

   Cargarlo desde Linux (remoteproc en el A35; la ruta/nombre del firmware depende de tu imagen Yocto):

```bash
cp build/zephyr/zephyr.elf /lib/firmware/adegi_m33.elf
echo adegi_m33.elf > /sys/class/remoteproc/remoteproc0/firmware
echo start > /sys/class/remoteproc/remoteproc0/state
```

## Qué es stub hoy

| Pieza | Stub | Real cuando… |
|---|---|---|
| `motor.c` | log de los permille | el overlay define `pwms` y `dir-gpios` en `/zephyr,user` |
| `link_stub.c` | guion que simula al A35 | se compila con `rpmsg.conf` + nodo `ipc0` |
| Calibración | `CONFIG_ADEGI_WHEEL_TRACK_MM=180`, `..._MAX_WHEEL_SPEED_MM_S=300` | se midan en el chasis real (menuconfig / `-D`) |

## Pendientes conocidos

- Sin rampa de aceleración (slew) ni lectura de encoders/odometría.
- Sin watchdog de hardware ni parada si falla `link_init` mientras está en movimiento (arranca en `idle`).
- Los sensores (MCXN947 por I3C) los lee el A35; el M33 recibe `DOCK_CONTACT`/`BATTERY_LOW` vía RPMsg.
