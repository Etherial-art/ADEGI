/*
 * M33 <-> A35 wire protocol over the RPMsg endpoint "adegi-ctrl".
 *
 * Binary on purpose (CLAUDE.md allows it when real time requires): the
 * velocity setpoint is sent at ~50 Hz and the M33 should not run a JSON
 * parser in its control path. RPMsg preserves message boundaries, so no
 * length prefix is needed. All integers are little-endian.
 *
 *   A35 -> M33
 *     0x01 SET_MODE      u8 mode        0 idle, 1 roam, 2 follow, 3 return_to_dock
 *     0x02 SET_VEL       i16 v_mm_s, i16 w_mrad_s
 *     0x03 DOCK_CONTACT  u8 (0/1)
 *     0x04 ALERT         u8 (0/1)       1 = fall detected, 0 = cleared by family/app
 *     0x05 BATTERY_LOW   u8 (0/1)
 *   M33 -> A35
 *     0x81 STATUS        u8 state, u8 flags, i16 left_pm, i16 right_pm
 *                        flags: bit0 alert, bit1 battery_low, bit2 vel_stale
 *
 * Full description in docs/ (see firmware/m33/README.md).
 */
#ifndef ADEGI_PROTOCOL_H
#define ADEGI_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>
#include "fsm.h"

#define PROTO_SET_MODE     0x01
#define PROTO_SET_VEL      0x02
#define PROTO_DOCK_CONTACT 0x03
#define PROTO_ALERT        0x04
#define PROTO_BATTERY_LOW  0x05
#define PROTO_STATUS       0x81

#define PROTO_STATUS_LEN   7

#define PROTO_FLAG_ALERT      (1u << 0)
#define PROTO_FLAG_BATT_LOW   (1u << 1)
#define PROTO_FLAG_VEL_STALE  (1u << 2)

/* 0 on success, negative errno-style value (-22 = bad message) otherwise. */
int proto_decode(const uint8_t *buf, size_t len, uint32_t now_ms, struct fsm_event *ev);

/* Returns bytes written, or 0 if cap is too small. */
size_t proto_encode_status(uint8_t *buf, size_t cap, uint8_t state, uint8_t flags,
			   int16_t left_pm, int16_t right_pm);

#endif /* ADEGI_PROTOCOL_H */
