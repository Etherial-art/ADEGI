/*
 * ADEGI M33 firmware: fixed-rate control loop.
 *
 *   link rx (ISR/thread) -> decode -> msgq -> [loop: FSM -> drive_mix -> motors]
 *                                                    \-> status back to the A35
 *
 * Events are queued instead of handled in the RPMsg callback so that all FSM
 * state is touched by exactly one thread (no locks needed).
 */
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include "drive.h"
#include "fsm.h"
#include "link.h"
#include "motor.h"
#include "protocol.h"

LOG_MODULE_REGISTER(adegi, LOG_LEVEL_INF);

#define STATUS_PERIOD_MS 100

K_MSGQ_DEFINE(ev_q, sizeof(struct fsm_event), 16, 4);

static void on_rx(const uint8_t *data, size_t len)
{
	struct fsm_event ev;

	if (proto_decode(data, len, k_uptime_get_32(), &ev) != 0) {
		LOG_WRN("dropping malformed message (%u bytes)", (unsigned int)len);
		return;
	}
	if (k_msgq_put(&ev_q, &ev, K_NO_WAIT) != 0) {
		LOG_WRN("event queue full, message dropped");
	}
}

int main(void)
{
	struct fsm fsm;
	struct fsm_event ev;
	struct fsm_output out;
	int16_t left = 0, right = 0;
	uint32_t last_status = 0;

	fsm_init(&fsm);

	if (motor_init() != 0) {
		LOG_ERR("motor init failed; refusing to run");
		return -1;
	}
	if (link_init(on_rx) != 0) {
		/* Degrade gracefully: stay in IDLE, motors off. */
		LOG_ERR("link init failed; running without A35");
	}

	LOG_INF("ADEGI M33 up, state=%s", fsm_state_name(fsm.state));

	int64_t next = k_uptime_get();

	while (1) {
		bool changed = false;

		while (k_msgq_get(&ev_q, &ev, K_NO_WAIT) == 0) {
			enum adegi_state prev = fsm.state;

			if (fsm_handle(&fsm, &ev)) {
				changed = true;
				LOG_INF("state %s -> %s", fsm_state_name(prev),
					fsm_state_name(fsm.state));
			}
		}

		uint32_t now = k_uptime_get_32();

		fsm_output(&fsm, now, &out);
		drive_mix(out.v_mm_s, out.w_mrad_s, &left, &right);
		motor_set(left, right);

		if (changed || (uint32_t)(now - last_status) >= STATUS_PERIOD_MS) {
			uint8_t buf[PROTO_STATUS_LEN];
			uint8_t flags = (out.alert_active ? PROTO_FLAG_ALERT : 0) |
					(fsm.battery_low ? PROTO_FLAG_BATT_LOW : 0) |
					(out.vel_stale ? PROTO_FLAG_VEL_STALE : 0);
			size_t n = proto_encode_status(buf, sizeof(buf), fsm.state, flags,
						       left, right);

			(void)link_send(buf, n); /* -ENOTCONN before bind is expected */
			last_status = now;
		}

		next += CONFIG_ADEGI_CONTROL_PERIOD_MS;
		k_sleep(K_TIMEOUT_ABS_MS(next));
	}
	return 0;
}
