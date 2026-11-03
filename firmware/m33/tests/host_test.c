/* Host-side unit tests for the pure-C parts. Run: make -C firmware/m33/tests */
#include <assert.h>
#include <stdio.h>
#include "../src/drive.h"
#include "../src/fsm.h"
#include "../src/protocol.h"

static struct fsm f;

static bool mode(uint8_t m, uint32_t t)
{
	struct fsm_event e = {.type = FSM_EV_MODE, .now_ms = t, .mode = m};
	return fsm_handle(&f, &e);
}
static void flagev(enum fsm_ev_type ty, bool v, uint32_t t)
{
	struct fsm_event e = {.type = ty, .now_ms = t, .flag = v};
	fsm_handle(&f, &e);
}
static void vel(int16_t v, int16_t w, uint32_t t)
{
	struct fsm_event e = {.type = FSM_EV_VELOCITY, .now_ms = t};
	e.vel.v_mm_s = v;
	e.vel.w_mrad_s = w;
	fsm_handle(&f, &e);
}

static void test_fsm(void)
{
	struct fsm_output o;

	fsm_init(&f);
	assert(f.state == ST_IDLE);

	/* Velocity in idle is ignored. */
	vel(100, 0, 0);
	fsm_output(&f, 0, &o);
	assert(o.v_mm_s == 0 && !o.vel_stale);

	/* Roam: no setpoint yet -> stale/stopped; then fresh; then dead-man timeout. */
	assert(mode(ST_ROAM, 10));
	fsm_output(&f, 10, &o);
	assert(o.v_mm_s == 0 && o.vel_stale);
	vel(120, 300, 20);
	fsm_output(&f, 30, &o);
	assert(o.v_mm_s == 120 && o.w_mrad_s == 300 && !o.vel_stale);
	fsm_output(&f, 20 + 501, &o);
	assert(o.v_mm_s == 0 && o.vel_stale);

	/* Low battery during roam -> return_to_dock, setpoint cleared, roam refused. */
	flagev(FSM_EV_BATTERY_LOW, true, 600);
	assert(f.state == ST_RETURN_TO_DOCK);
	fsm_output(&f, 600, &o);
	assert(o.v_mm_s == 0);
	mode(ST_ROAM, 610);
	assert(f.state == ST_RETURN_TO_DOCK);

	/* Dock contact -> charging, motors off even if velocity arrives. */
	flagev(FSM_EV_DOCK_CONTACT, true, 700);
	assert(f.state == ST_CHARGING);
	vel(100, 0, 710);
	fsm_output(&f, 710, &o);
	assert(o.v_mm_s == 0);

	/* Battery recovers, family/A35 asks follow -> leaves dock. */
	flagev(FSM_EV_BATTERY_LOW, false, 800);
	assert(f.state == ST_CHARGING);
	assert(mode(ST_FOLLOW, 810));

	/* Alert from any state; modes ignored until cleared. */
	vel(100, 0, 820);
	flagev(FSM_EV_ALERT, true, 830);
	assert(f.state == ST_ALERT);
	fsm_output(&f, 830, &o);
	assert(o.alert_active && o.v_mm_s == 0);
	assert(!mode(ST_ROAM, 840));
	assert(f.state == ST_ALERT);
	flagev(FSM_EV_ALERT, false, 850);
	assert(f.state == ST_IDLE);

	/* Timestamp wrap-around keeps the dead-man correct. */
	mode(ST_ROAM, 0xFFFFFFF0u);
	vel(50, 0, 0xFFFFFFF8u);
	fsm_output(&f, 0x00000010u, &o); /* 24 ms later across wrap */
	assert(o.v_mm_s == 50);

	/* Invalid mode (charging/alert are not commandable). */
	assert(!mode(ST_CHARGING, 5));
	assert(!mode(ST_ALERT, 5));
}

static void test_drive(void)
{
	int16_t l, r;

	drive_mix(0, 0, &l, &r);
	assert(l == 0 && r == 0);

	drive_mix(150, 0, &l, &r); /* half of 300 mm/s */
	assert(l == 500 && r == 500);

	drive_mix(0, 1000, &l, &r); /* spin CCW: left back, right forward */
	assert(l < 0 && r > 0 && l == -r);

	drive_mix(-150, 0, &l, &r);
	assert(l == -500 && r == -500);

	/* Saturation keeps the ratio and the limit. */
	drive_mix(300, 2000, &l, &r);
	assert(r == 1000 && l < r && l >= -1000);
	drive_mix(32767, 32767, &l, &r);
	assert(l >= -1000 && l <= 1000 && r >= -1000 && r <= 1000);
}

static void test_protocol(void)
{
	struct fsm_event e;
	uint8_t vel_msg[] = {PROTO_SET_VEL, 0x9C, 0xFF, 0xF4, 0x01}; /* -100, 500 */
	uint8_t bad_mode[] = {PROTO_SET_MODE, 4};
	uint8_t st[PROTO_STATUS_LEN];

	assert(proto_decode(vel_msg, sizeof vel_msg, 42, &e) == 0);
	assert(e.type == FSM_EV_VELOCITY && e.vel.v_mm_s == -100 && e.vel.w_mrad_s == 500);
	assert(e.now_ms == 42);
	assert(proto_decode(bad_mode, sizeof bad_mode, 0, &e) < 0);
	assert(proto_decode(vel_msg, 3, 0, &e) < 0);
	assert(proto_decode(vel_msg, 0, 0, &e) < 0);

	uint8_t al[] = {PROTO_ALERT, 1};
	assert(proto_decode(al, 2, 0, &e) == 0 && e.type == FSM_EV_ALERT && e.flag);

	assert(proto_encode_status(st, sizeof st, ST_ALERT, PROTO_FLAG_ALERT, -500, 1000) == 7);
	assert(st[0] == 0x81 && st[1] == ST_ALERT && st[2] == 1);
	assert(st[3] == 0x0C && st[4] == 0xFE && st[5] == 0xE8 && st[6] == 0x03);
	assert(proto_encode_status(st, 3, 0, 0, 0, 0) == 0);
}

int main(void)
{
	test_fsm();
	test_drive();
	test_protocol();
	puts("all host tests passed");
	return 0;
}
