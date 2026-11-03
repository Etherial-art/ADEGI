#include "drive.h"
#include <stdlib.h>

#ifndef CONFIG_ADEGI_WHEEL_TRACK_MM
#define CONFIG_ADEGI_WHEEL_TRACK_MM 180
#endif
#ifndef CONFIG_ADEGI_MAX_WHEEL_SPEED_MM_S
#define CONFIG_ADEGI_MAX_WHEEL_SPEED_MM_S 300
#endif

void drive_mix(int16_t v_mm_s, int16_t w_mrad_s, int16_t *left_pm, int16_t *right_pm)
{
	/* v_wheel = v -/+ w * (track / 2); mrad/s * mm / 1000 -> mm/s */
	int32_t dv = ((int32_t)w_mrad_s * CONFIG_ADEGI_WHEEL_TRACK_MM) / 2000;
	int32_t l = ((int32_t)v_mm_s - dv) * 1000 / CONFIG_ADEGI_MAX_WHEEL_SPEED_MM_S;
	int32_t r = ((int32_t)v_mm_s + dv) * 1000 / CONFIG_ADEGI_MAX_WHEEL_SPEED_MM_S;

	int32_t peak = abs(l) > abs(r) ? abs(l) : abs(r);

	if (peak > 1000) {
		l = l * 1000 / peak;
		r = r * 1000 / peak;
	}

	*left_pm = (int16_t)l;
	*right_pm = (int16_t)r;
}
