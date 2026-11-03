/* Differential-drive kinematics (pure C). */
#ifndef ADEGI_DRIVE_H
#define ADEGI_DRIVE_H

#include <stdint.h>

/*
 * Converts body velocity (v mm/s, w mrad/s) into signed wheel commands in
 * permille of full PWM (-1000..1000). If either wheel would exceed 100%,
 * both are scaled by the same factor so the commanded turning radius is kept
 * (clipping each wheel alone would silently change the trajectory).
 */
void drive_mix(int16_t v_mm_s, int16_t w_mrad_s, int16_t *left_pm, int16_t *right_pm);

#endif /* ADEGI_DRIVE_H */
