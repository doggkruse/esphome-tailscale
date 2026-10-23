#include <cassert>
#include <cstring>
#define CONFIG_ML_NO_PSRAM 1
#include "microlink/components/microlink/include/ml_derp_store.h"
static void *fail(size_t) { return nullptr; }
int main() {
    ml_derp_region_t region = {};
    const size_t lengths[ML_MAX_DERP_NODES] = {63,63,63,63};
    assert(ml_derp_region_allocate_names(&region, 4, lengths, malloc));
    region.node_count = 4;
    strcpy(region.nodes[3].hostname, "last.example");
    auto *before = region.nodes;
    assert(!ml_derp_region_allocate_names(&region, 5, lengths, malloc));
    assert(!ml_derp_region_allocate_names(&region, 2, lengths, fail));
    assert(region.nodes == before && region.node_count == 4);
    assert(!strcmp(region.nodes[3].hostname, "last.example"));
    for (int i=0;i<100;i++) {
        assert(ml_derp_region_allocate_names(&region, 1, lengths, malloc));
        assert(region.node_count == 0 && region.nodes[0].hostname[0] == 0);
        assert(ml_derp_region_allocate_names(&region, 4, lengths, malloc));
    }
    assert(ml_derp_region_allocate_names(&region, 0, nullptr, malloc));
    assert(region.nodes == nullptr);
    ml_derp_region_clear(&region);
    const size_t sizes[] = {0,1,63,12};
    assert(ml_derp_region_allocate_names(&region, 4, sizes, malloc));
    strcpy(region.nodes[1].hostname, "x");
    memset(region.nodes[2].hostname, 'a', 63);
    strcpy(region.nodes[3].hostname, "last.example");
    assert(region.nodes[0].hostname[0]==0);
    assert(strlen(region.nodes[1].hostname)==1 && strlen(region.nodes[2].hostname)==63);
    assert(!strcmp(region.nodes[3].hostname,"last.example"));
    const size_t oversized[] = {64};
    before=region.nodes;
    assert(!ml_derp_region_allocate_names(&region, 1, oversized, malloc));
    assert(region.nodes==before);
    ml_derp_region_clear(&region);
}
