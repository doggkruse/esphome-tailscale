#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#define ML_MAX_DERP_REGIONS 32
#define ML_MAX_DERP_NODES 4

typedef struct {
#ifdef CONFIG_ML_NO_PSRAM
    char *hostname;
#else
    char hostname[64];
#endif
    char ipv4[16];
#ifndef CONFIG_ML_NO_PSRAM
    char ipv6[46];
#endif
    uint16_t stun_port;
    uint16_t derp_port;
    bool stun_only;
} ml_derp_node_t;

typedef struct {
    uint16_t region_id;
    char code[8];
    char name[24];
#ifdef CONFIG_ML_NO_PSRAM
    ml_derp_node_t *nodes;
#else
    ml_derp_node_t nodes[ML_MAX_DERP_NODES];
#endif
    uint8_t node_count;
    bool avoid;
} ml_derp_region_t;

#ifdef CONFIG_ML_NO_PSRAM
static inline void ml_derp_region_clear(ml_derp_region_t *region) {
    free(region->nodes);
    memset(region, 0, sizeof(*region));
}

/* Allocate exactly the populated, bounded node count. Callers serialize readers
 * and replacement. A failed allocation leaves the old region intact. */
static inline bool ml_derp_region_allocate_names(ml_derp_region_t *region, size_t count,
                                               const size_t *name_lengths,
                                               void *(*allocate)(size_t)) {
    if (count > ML_MAX_DERP_NODES || (count && !name_lengths)) return false;
    size_t bytes = count * sizeof(ml_derp_node_t);
    for (size_t i=0; i<count; i++) {
        if (name_lengths[i] > 63) return false;
        bytes += name_lengths[i] + 1;
    }
    ml_derp_node_t *nodes = count ? (ml_derp_node_t *)allocate(bytes) : NULL;
    if (count && !nodes) return false;
    if (nodes) {
        memset(nodes, 0, bytes);
        char *names = (char *)(nodes + count);
        for (size_t i=0; i<count; i++) {
            nodes[i].hostname = names;
            names += name_lengths[i] + 1;
        }
    }
    ml_derp_region_clear(region);
    region->nodes = nodes;
    return true;
}
#endif
