/* Transport to the A35. Implemented by link_rpmsg.c (real) or link_stub.c. */
#ifndef ADEGI_LINK_H
#define ADEGI_LINK_H

#include <stddef.h>
#include <stdint.h>

/* Called from the transport's context (ISR/thread): keep it short, no blocking. */
typedef void (*link_rx_cb)(const uint8_t *data, size_t len);

int link_init(link_rx_cb cb);

/* Returns 0 on success, negative errno otherwise (-ENOTCONN if peer not bound). */
int link_send(const uint8_t *data, size_t len);

#endif /* ADEGI_LINK_H */
