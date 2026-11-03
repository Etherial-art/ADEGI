/*
 * Motor driver for a DIR+PWM H-bridge per motor.
 *
 * The real path is compiled only when the board overlay defines, under
 * /zephyr,user:  pwms = <left>, <right>;  dir-gpios = <left>, <right>;
 * (see boards/stm32mp257f_dk_stm32mp257xx_m33.overlay.example).
 * Otherwise a stub just logs changes, so the app builds and runs anywhere
 * (including native_sim) before the power stage exists.
 */
#include <stdlib.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include "motor.h"

LOG_MODULE_REGISTER(motor, LOG_LEVEL_INF);

#define ZU DT_PATH(zephyr_user)

#if DT_NODE_HAS_PROP(ZU, pwms) && DT_NODE_HAS_PROP(ZU, dir_gpios)

#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/pwm.h>

static const struct pwm_dt_spec pwm[2] = {
	PWM_DT_SPEC_GET_BY_IDX(ZU, 0),
	PWM_DT_SPEC_GET_BY_IDX(ZU, 1),
};
static const struct gpio_dt_spec dir[2] = {
	GPIO_DT_SPEC_GET_BY_IDX(ZU, dir_gpios, 0),
	GPIO_DT_SPEC_GET_BY_IDX(ZU, dir_gpios, 1),
};

int motor_init(void)
{
	for (int i = 0; i < 2; i++) {
		if (!pwm_is_ready_dt(&pwm[i]) || !gpio_is_ready_dt(&dir[i])) {
			LOG_ERR("motor %d: PWM/GPIO device not ready", i);
			return -ENODEV;
		}
		int ret = gpio_pin_configure_dt(&dir[i], GPIO_OUTPUT_INACTIVE);

		if (ret < 0) {
			return ret;
		}
		/* Start stopped. */
		ret = pwm_set_dt(&pwm[i], pwm[i].period, 0);
		if (ret < 0) {
			return ret;
		}
	}
	LOG_INF("motors: real PWM driver");
	return 0;
}

static void set_one(int i, int16_t pm)
{
	uint32_t mag = (uint32_t)abs(pm);

	if (mag > 1000) {
		mag = 1000;
	}
	/* DIR pin active = forward. Flip a motor with GPIO_ACTIVE_LOW in the overlay. */
	gpio_pin_set_dt(&dir[i], pm >= 0);
	pwm_set_dt(&pwm[i], pwm[i].period, (uint32_t)(((uint64_t)pwm[i].period * mag) / 1000));
}

void motor_set(int16_t left_pm, int16_t right_pm)
{
	set_one(0, left_pm);
	set_one(1, right_pm);
}

#else /* ---- stub ---- */

static int16_t last_l, last_r;

int motor_init(void)
{
	LOG_WRN("motors: STUB (no pwms/dir-gpios in /zephyr,user)");
	return 0;
}

void motor_set(int16_t left_pm, int16_t right_pm)
{
	if (left_pm != last_l || right_pm != last_r) {
		LOG_INF("motor stub: L=%d R=%d (permille)", left_pm, right_pm);
		last_l = left_pm;
		last_r = right_pm;
	}
}

#endif
