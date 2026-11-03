/*
 * Stub link: replays a scripted conversation, as if the A35 were sending it,
 * and logs what the M33 would send back. Lets you watch the whole state
 * machine run on native_sim or on the board with no Linux side.
 */
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include "link.h"

LOG_MODULE_REGISTER(link, LOG_LEVEL_INF);

struct step {
	uint32_t delay_ms;
	uint8_t len;
	uint8_t msg[5];
};

/* mode=roam, drive, battery low (-> return_to_dock), dock contact (-> charging),
 * mode=idle, fall alert, alert cleared. Velocity 150 mm/s, 0.5 rad/s. */
static const struct step script[] = {
	{1000, 2, {0x01, 0x01}},
	{200, 5, {0x02, 150, 0, 0xF4, 0x01}},
	{200, 5, {0x02, 150, 0, 0xF4, 0x01}},
	{1500, 2, {0x05, 0x01}},
	{200, 5, {0x02, 100, 0, 0, 0}},
	{1000, 2, {0x03, 0x01}},
	{2000, 2, {0x01, 0x00}},
	{1000, 2, {0x04, 0x01}},
	{2000, 2, {0x04, 0x00}},
};

static link_rx_cb rx_cb;

static void script_thread(void *a, void *b, void *c)
{
	for (size_t i = 0; i < ARRAY_SIZE(script); i++) {
		k_msleep(script[i].delay_ms);
		rx_cb(script[i].msg, script[i].len);
	}
	LOG_INF("stub script finished");
}

K_THREAD_STACK_DEFINE(script_stack, 1024);
static struct k_thread script_thr;

int link_init(link_rx_cb cb)
{
	rx_cb = cb;
	LOG_WRN("link: STUB (scripted A35 traffic, no RPMsg)");
	k_thread_create(&script_thr, script_stack, K_THREAD_STACK_SIZEOF(script_stack),
			script_thread, NULL, NULL, NULL, K_PRIO_PREEMPT(10), 0, K_NO_WAIT);
	return 0;
}

int link_send(const uint8_t *data, size_t len)
{
	LOG_DBG("tx %u bytes, type 0x%02x", (unsigned int)len, data[0]);
	return 0;
}
