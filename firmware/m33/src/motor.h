/* Two-motor PWM driver. Real hardware if devicetree wires it, stub otherwise. */
#ifndef ADEGI_MOTOR_H
#define ADEGI_MOTOR_H

#include <stdint.h>

int motor_init(void);

/* Signed permille of full duty: -1000 (full reverse) .. +1000 (full forward). */
void motor_set(int16_t left_pm, int16_t right_pm);

#endif /* ADEGI_MOTOR_H */
