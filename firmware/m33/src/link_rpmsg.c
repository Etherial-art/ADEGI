/*
 * RPMsg link through Zephyr's ipc_service (OpenAMP backend).
 *
 * The A35 (Linux) is the RPMsg host; this firmware is the remote. Linux sees
 * a name-service announcement for "adegi-ctrl" and can open it as an rpmsg
 * char device. Requires an "ipc0" node (shared-memory region, IPM mailbox):
 * see boards/stm32mp257f_dk_stm32mp257xx_m33.overlay.example.
 */
#include <errno.h>
#include <zephyr/ipc/ipc_service.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include "link.h"

LOG_MODULE_REGISTER(link, LOG_LEVEL_INF);

static struct ipc_ept ept;
static link_rx_cb rx_cb;
static atomic_t bound;

static void ept_bound(void *priv)
{
	atomic_set(&bound, 1);
	LOG_INF("rpmsg endpoint bound");
}

static void ept_received(const void *data, size_t len, void *priv)
{
	if (rx_cb) {
		rx_cb(data, len);
	}
}

static struct ipc_ept_cfg ept_cfg = {
	.name = "adegi-ctrl",
	.cb = {
		.bound = ept_bound,
		.received = ept_received,
	},
};

int link_init(link_rx_cb cb)
{
	const struct device *ipc = DEVICE_DT_GET(DT_NODELABEL(ipc0));
	int ret;

	rx_cb = cb;
	ret = ipc_service_open_instance(ipc);
	if (ret < 0 && ret != -EALREADY) {
		LOG_ERR("ipc_service_open_instance: %d", ret);
		return ret;
	}
	ret = ipc_service_register_endpoint(ipc, &ept, &ept_cfg);
	if (ret < 0) {
		LOG_ERR("ipc_service_register_endpoint: %d", ret);
	}
	return ret;
}

int link_send(const uint8_t *data, size_t len)
{
	if (!atomic_get(&bound)) {
		return -ENOTCONN;
	}
	int ret = ipc_service_send(&ept, data, len);

	return ret < 0 ? ret : 0;
}
