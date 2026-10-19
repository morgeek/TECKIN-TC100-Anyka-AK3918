/* netacl.c: allowed source addresses (TC100_NET_ALLOW). Addresses in network order. */
#ifndef TC100_NETACL_H
#define TC100_NETACL_H
#include <stdint.h>
int netacl_allowed(uint32_t addr);
int netacl_is_private(uint32_t addr);
#endif
