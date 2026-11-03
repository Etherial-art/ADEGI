#include "fsm.h"

#ifndef CONFIG_ADEGI_VEL_TIMEOUT_MS
#define CONFIG_ADEGI_VEL_TIMEOUT_MS 500
#endif

static bool is_moving_state(enum adegi_state s)
{
	return s == ST_ROAM || s == ST_FOLLOW || s == ST_RETURN_TO_DOCK;
}

static void enter(struct fsm *f, enum adegi_state s)
{
	f->state = s;
	/* Never inherit an old setpoint into a new state. */
	f->have_vel = false;
	f->v_mm_s = 0;
	f->w_mrad_s = 0;
}

void fsm_init(struct fsm *f)
{
	f->battery_low = false;
	enter(f, ST_IDLE);
	f->last_vel_ms = 0;
}

bool fsm_handle(struct fsm *f, const struct fsm_event *ev)
{
	enum adegi_state before = f->state;

	switch (ev->type) {
	case FSM_EV_ALERT:
		if (ev->flag) {
			if (f->state != ST_ALERT) {
				enter(f, ST_ALERT);
			}
		} else if (f->state == ST_ALERT) {
			enter(f, ST_IDLE);
		}
		break;

	case FSM_EV_MODE:
		/* Alert must be cleared explicitly; mode commands are ignored meanwhile. */
		if (f->state == ST_ALERT || ev->mode > ST_RETURN_TO_DOCK) {
			break;
		}
		if (f->battery_low && (ev->mode == ST_ROAM || ev->mode == ST_FOLLOW)) {
			/* Low battery: refuse to wander, go charge instead. */
			if (f->state != ST_CHARGING) {
				enter(f, ST_RETURN_TO_DOCK);
			}
			break;
		}
		if ((enum adegi_state)ev->mode != f->state) {
			enter(f, (enum adegi_state)ev->mode);
		}
		break;

	case FSM_EV_VELOCITY:
		if (is_moving_state(f->state)) {
			f->v_mm_s = ev->vel.v_mm_s;
			f->w_mrad_s = ev->vel.w_mrad_s;
			f->last_vel_ms = ev->now_ms;
			f->have_vel = true;
		}
		break;

	case FSM_EV_DOCK_CONTACT:
		if (ev->flag && f->state == ST_RETURN_TO_DOCK) {
			enter(f, ST_CHARGING);
		} else if (!ev->flag && f->state == ST_CHARGING) {
			/* Contact lost without a mode command: do not just sit there. */
			enter(f, f->battery_low ? ST_RETURN_TO_DOCK : ST_IDLE);
		}
		break;

	case FSM_EV_BATTERY_LOW:
		f->battery_low = ev->flag;
		if (ev->flag && (f->state == ST_ROAM || f->state == ST_FOLLOW ||
				 f->state == ST_IDLE)) {
			enter(f, ST_RETURN_TO_DOCK);
		}
		break;
	}

	return f->state != before;
}

void fsm_output(const struct fsm *f, uint32_t now_ms, struct fsm_output *out)
{
	out->v_mm_s = 0;
	out->w_mrad_s = 0;
	out->vel_stale = false;
	out->alert_active = (f->state == ST_ALERT);

	if (!is_moving_state(f->state)) {
		return;
	}

	/* Unsigned subtraction stays correct across uint32 wrap-around. */
	bool fresh = f->have_vel &&
		     (uint32_t)(now_ms - f->last_vel_ms) <= CONFIG_ADEGI_VEL_TIMEOUT_MS;

	if (fresh) {
		out->v_mm_s = f->v_mm_s;
		out->w_mrad_s = f->w_mrad_s;
	} else {
		out->vel_stale = true; /* dead-man: A35 crashed or link dropped */
	}
}

const char *fsm_state_name(enum adegi_state s)
{
	switch (s) {
	case ST_IDLE: return "idle";
	case ST_ROAM: return "roam";
	case ST_FOLLOW: return "follow";
	case ST_RETURN_TO_DOCK: return "return_to_dock";
	case ST_CHARGING: return "charging";
	case ST_ALERT: return "alert";
	}
	return "?";
}
