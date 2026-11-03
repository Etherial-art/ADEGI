#include "protocol.h"

#define PROTO_EINVAL (-22)

static int16_t rd_i16(const uint8_t *p)
{
	return (int16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static void wr_i16(uint8_t *p, int16_t v)
{
	p[0] = (uint8_t)((uint16_t)v & 0xff);
	p[1] = (uint8_t)(((uint16_t)v >> 8) & 0xff);
}

int proto_decode(const uint8_t *buf, size_t len, uint32_t now_ms, struct fsm_event *ev)
{
	if (buf == NULL || ev == NULL || len < 1) {
		return PROTO_EINVAL;
	}

	ev->now_ms = now_ms;

	switch (buf[0]) {
	case PROTO_SET_MODE:
		if (len != 2 || buf[1] > ST_RETURN_TO_DOCK) {
			return PROTO_EINVAL;
		}
		ev->type = FSM_EV_MODE;
		ev->mode = buf[1];
		return 0;

	case PROTO_SET_VEL:
		if (len != 5) {
			return PROTO_EINVAL;
		}
		ev->type = FSM_EV_VELOCITY;
		ev->vel.v_mm_s = rd_i16(&buf[1]);
		ev->vel.w_mrad_s = rd_i16(&buf[3]);
		return 0;

	case PROTO_DOCK_CONTACT:
	case PROTO_ALERT:
	case PROTO_BATTERY_LOW:
		if (len != 2 || buf[1] > 1) {
			return PROTO_EINVAL;
		}
		ev->type = buf[0] == PROTO_DOCK_CONTACT ? FSM_EV_DOCK_CONTACT :
			   buf[0] == PROTO_ALERT ? FSM_EV_ALERT : FSM_EV_BATTERY_LOW;
		ev->flag = buf[1] != 0;
		return 0;

	default:
		return PROTO_EINVAL;
	}
}

size_t proto_encode_status(uint8_t *buf, size_t cap, uint8_t state, uint8_t flags,
			   int16_t left_pm, int16_t right_pm)
{
	if (cap < PROTO_STATUS_LEN) {
		return 0;
	}
	buf[0] = PROTO_STATUS;
	buf[1] = state;
	buf[2] = flags;
	wr_i16(&buf[3], left_pm);
	wr_i16(&buf[5], right_pm);
	return PROTO_STATUS_LEN;
}
