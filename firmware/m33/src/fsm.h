/*
 * ADEGI behaviour state machine (low-level, runs on the M33).
 *
 * Pure C, no Zephyr dependencies, so it can be unit-tested on the host.
 * High-level decisions (where to go, whom to follow) live on the A35;
 * the M33 only enforces safe, deterministic state handling and drives motors.
 */
#ifndef ADEGI_FSM_H
#define ADEGI_FSM_H

#include <stdbool.h>
#include <stdint.h>

enum adegi_state {
	ST_IDLE = 0,
	ST_ROAM = 1,
	ST_FOLLOW = 2,
	ST_RETURN_TO_DOCK = 3,
	ST_CHARGING = 4,
	ST_ALERT = 5,
};

/* Values 0..3 are also the wire values of SET_MODE (see protocol.h). */

enum fsm_ev_type {
	FSM_EV_MODE,         /* .mode: requested adegi_state (IDLE/ROAM/FOLLOW/RETURN) */
	FSM_EV_VELOCITY,     /* .vel: body velocity setpoint from the A35 */
	FSM_EV_DOCK_CONTACT, /* .flag: charging contacts touching the dock */
	FSM_EV_ALERT,        /* .flag: true = fall/emergency, false = cleared */
	FSM_EV_BATTERY_LOW,  /* .flag */
};

struct fsm_event {
	enum fsm_ev_type type;
	uint32_t now_ms;
	union {
		uint8_t mode;
		bool flag;
		struct {
			int16_t v_mm_s;      /* forward speed */
			int16_t w_mrad_s;    /* yaw rate, positive = counter-clockwise */
		} vel;
	};
};

struct fsm_output {
	int16_t v_mm_s;
	int16_t w_mrad_s;
	bool alert_active;
	bool vel_stale;   /* moving state but setpoint missing/expired -> stopped */
};

struct fsm {
	enum adegi_state state;
	bool battery_low;
	bool have_vel;
	int16_t v_mm_s;
	int16_t w_mrad_s;
	uint32_t last_vel_ms;
};

void fsm_init(struct fsm *f);

/* Returns true if the state changed. */
bool fsm_handle(struct fsm *f, const struct fsm_event *ev);

/* Computes what the actuators should do right now. */
void fsm_output(const struct fsm *f, uint32_t now_ms, struct fsm_output *out);

const char *fsm_state_name(enum adegi_state s);

#endif /* ADEGI_FSM_H */
