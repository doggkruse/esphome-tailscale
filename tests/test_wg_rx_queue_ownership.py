"""Actual WG queue producers/consumer against a bounded RTOS ownership adapter.

This checks nonblocking admission, payload lifetime, and recovery after a full
queue. It does not emulate FreeRTOS scheduling, WireGuard crypto, or a supported
traffic rate.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
STACK = ROOT / "microlink/components/microlink"


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}", start) + 2]


@pytest.fixture(scope="module",
                params=[False, True], ids=["normal32", "no_psram16"])
def queue_fixture(request, tmp_path_factory):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    header = (STACK / "include/microlink_internal.h").read_text()
    constants = "/*\n" + header[header.index(" * Constants\n"):header.index("/* Protocol limits */")]
    start = header.index("typedef struct {", header.index("/* Received packet"))
    packet = header[start:header.index("} ml_rx_packet_t;", start) + len("} ml_rx_packet_t;")]
    udp = (STACK / "src/ml_net_io.c").read_text()
    derp = (STACK / "src/ml_derp.c").read_text()
    wg = (STACK / "src/ml_wg_mgr.c").read_text()
    lifecycle = (STACK / "src/microlink.c").read_text()
    start = lifecycle.index("    {\n        ml_rx_packet_t pkt;", lifecycle.index("void microlink_destroy("))
    cleanup = lifecycle[start:lifecycle.index("\n    /* Delete queues */", start)]
    source = PREAMBLE + constants + packet + ADAPTER
    for name, text, route in [("direct", udp, "route_udp_packet"), ("relay", derp, "route_derp_packet")]:
        source += f"\nnamespace {name} {{\n" + CLASSIFICATION_TYPES
        source += function(text, "static pkt_type_t classify_packet(")
        source += function(text, f"static void {route}(") + "\n}\n"
    source += function(wg, "static void process_wg_packet(")
    source += "\nstatic void discard_pending(microlink_t *ml) {\n" + cleanup + "\n}\n"
    source += CHECKS
    directory = tmp_path_factory.mktemp("wg-rx-queue")
    test = directory / "queue.cpp"
    binary = directory / "queue"
    test.write_text(source)
    no_psram = request.param
    flags = []
    if no_psram:
        flags.append("-DCONFIG_ML_NO_PSRAM=1")
    subprocess.run([compiler, "-std=c++20", "-fsanitize=address,undefined",
                    "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                    *flags, str(test), "-o", str(binary)], check=True)
    return binary, 16 if no_psram else 32


@pytest.mark.parametrize("scenario", ["burst", "no_netif", "no_device", "no_pbuf", "cleanup", "disco"])
def test_wg_rx_ownership_and_recovery(queue_fixture, scenario):
    binary, capacity = queue_fixture
    subprocess.run([str(binary), str(capacity), scenario],
                   check=True, timeout=10)


PREAMBLE = r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <vector>
#include <arpa/inet.h>
#define ESP_LOGD(...) ((void)0)
using TickType_t = uint32_t;
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
'''

CLASSIFICATION_TYPES = r'''
static const uint8_t DISCO_MAGIC[6] = {'T', 'S', 0xf0, 0x9f, 0x92, 0xac};
enum pkt_type_t { PKT_DISCO, PKT_STUN, PKT_WIREGUARD, PKT_UNKNOWN };
'''

ADAPTER = r'''
struct FakeQueue { size_t capacity; std::deque<ml_rx_packet_t> entries; };
using QueueHandle_t = FakeQueue *;
constexpr int pdTRUE=1, pdFALSE=0;
static int xQueueSend(FakeQueue *q, const ml_rx_packet_t *packet, TickType_t wait) {
    assert(q && wait == 0);
    if (q->entries.size() == q->capacity) return pdFALSE;
    q->entries.push_back(*packet); return pdTRUE;
}
static int xQueueReceive(FakeQueue *q, void *packet, int wait) {
    assert(q && wait == 0);
    if (q->entries.empty()) return pdFALSE;
    memcpy(packet, &q->entries.front(), sizeof(ml_rx_packet_t));
    q->entries.pop_front(); return pdTRUE;
}
struct ml_peer_update_t {};
struct netif { void *state; };
struct microlink_t {
    FakeQueue *disco_rx_queue, *wg_rx_queue, *stun_rx_queue;
    FakeQueue *peer_update_queue=nullptr;
    void *wg_netif;
};
static std::map<void *, unsigned> live;
static std::map<unsigned, unsigned> frees;
static std::map<unsigned, std::vector<uint8_t>> expected;
static unsigned serial=0;
static uint8_t *payload(size_t size=64) {
    assert(size >= 8);
    auto *p=static_cast<uint8_t *>(malloc(size)); assert(p);
    unsigned id=++serial;
    memset(p, int(id & 0xff), size); p[0]=4; p[1]=0;
    memcpy(p+4, &id, sizeof(id));
    assert(live.emplace(p,id).second);
    expected[id]=std::vector<uint8_t>(p,p+size); return p;
}
static void release(void *p) {
    auto it=live.find(p); assert(it!=live.end());
    assert(++frees[it->second]==1); live.erase(it); free(p);
}
#define free release
struct pbuf { std::vector<uint8_t> bytes; };
constexpr int PBUF_RAW=0, PBUF_RAM=1, IPADDR_TYPE_V4=0;
static bool fail_pbuf=false;
static std::vector<pbuf *> held;
static unsigned pbuf_live=0;
static pbuf *pbuf_alloc(int layer, size_t size, int type) {
    assert(layer==PBUF_RAW && type==PBUF_RAM);
    if (fail_pbuf) return nullptr;
    ++pbuf_live; return new pbuf{std::vector<uint8_t>(size)};
}
static int pbuf_take(pbuf *p, const void *data, size_t size) {
    assert(p->bytes.size()==size && live.count(const_cast<void *>(data))==1);
    memcpy(p->bytes.data(),data,size); return 0;
}
struct ip_addr_t { uint32_t ip=0; };
static void ip_addr_set_any(bool ipv6, ip_addr_t *a) { assert(!ipv6); a->ip=0; }
#define IP_SET_TYPE_VAL(a,t) ((void)0)
static ip_addr_t *ip_2_ip4(ip_addr_t *a) { return a; }
static void ip4_addr_set_u32(ip_addr_t *a, uint32_t value) { a->ip=value; }
struct Delivery { unsigned id; uint32_t ip; uint16_t port; };
static std::vector<Delivery> deliveries;
static void wireguardif_network_rx(void *device, void *pcb, pbuf *p,
                                   const ip_addr_t *addr, uint16_t port) {
    assert(device && !pcb);
    unsigned id; memcpy(&id,p->bytes.data()+4,sizeof(id));
    assert(frees[id]==1 && p->bytes==expected.at(id));
    deliveries.push_back({id,addr->ip,port});
    held.push_back(p); // Retain the independent copy beyond caller return.
}
'''

CHECKS = r'''
static void release_copies() {
    for (auto *p:held) { assert(pbuf_live); --pbuf_live; delete p; }
    held.clear();
}
static unsigned send(microlink_t *ml, bool relay, size_t size=64) {
    auto *data=payload(size); unsigned id=serial;
    const uint8_t key[32]={0xa5};
    if (relay) relay::route_derp_packet(ml,data,size,key);
    else direct::route_udp_packet(ml,data,size,0xc0000201,12345);
    return id;
}
static void consume_one(microlink_t *ml) {
    ml_rx_packet_t pkt{};
    assert(xQueueReceive(ml->wg_rx_queue,&pkt,0)==pdTRUE);
    if (pkt.via_derp) assert(pkt.src_pubkey[0]==0xa5 && pkt.src_port==0);
    else assert(pkt.src_ip==0xc0000201 && pkt.src_port==12345);
    process_wg_packet(ml,&pkt);
}
int main(int argc, char **argv) {
    assert(argc==3);
    size_t capacity=strtoul(argv[1],nullptr,10);
    assert(ML_WG_RX_QUEUE_DEPTH==capacity);
    FakeQueue wg{capacity}, disco{8}, stun{4};
    int device=1; netif nif{&device};
    microlink_t ml{&disco,&wg,&stun,nullptr,&nif};
    const char *scenario=argv[2];
    if (!strcmp(scenario,"burst")) {
        // Alternate real direct/relay producers into the same finite queue.
        std::vector<unsigned> accepted;
        for (unsigned round=0;round<3;++round) {
            accepted.clear(); deliveries.clear();
            for (size_t i=0;i<capacity;++i) accepted.push_back(send(&ml,i%2));
            assert(wg.entries.size()==capacity && live.size()==capacity);
            for (bool relay:{false,true}) {
                unsigned dropped=send(&ml,relay);
                assert(frees[dropped]==1 && live.size()==capacity);
            }
            consume_one(&ml); // Space becomes reusable without queue recreation.
            accepted.push_back(send(&ml,true,1564));
            while (!wg.entries.empty()) consume_one(&ml);
            assert(deliveries.size()==accepted.size() && live.empty());
            for (size_t i=0;i<accepted.size();++i) {
                assert(deliveries[i].id==accepted[i]);
                bool relay=(i==capacity || i%2);
                assert(deliveries[i].ip==(relay?0:htonl(0xc0000201)));
                assert(deliveries[i].port==(relay?0:12345));
                assert(held[i]->bytes==expected.at(accepted[i]));
            }
            release_copies();
        }
    } else if (!strcmp(scenario,"disco")) {
        auto disco_send=[&](bool relay) {
            auto *data=payload(); unsigned id=serial;
            memcpy(data,direct::DISCO_MAGIC,6);
            expected[id]=std::vector<uint8_t>(data,data+64);
            const uint8_t key[32]={0xa5};
            if (relay) relay::route_derp_packet(&ml,data,64,key);
            else direct::route_udp_packet(&ml,data,64,0xc0000201,12345);
            return id;
        };
        for (size_t i=0;i<disco.capacity;++i) disco_send(i%2);
        for (bool relay:{false,true}) {
            unsigned dropped=disco_send(relay);
            assert(frees[dropped]==1);
        }
        assert(wg.entries.empty() && disco.entries.size()==disco.capacity);
        discard_pending(&ml); // Retains actual production payload cleanup for DISCO.
        assert(disco.entries.empty() && live.empty());
    } else if (!strcmp(scenario,"cleanup")) {
        for (size_t i=0;i<capacity;++i) send(&ml,i%2);
        discard_pending(&ml); // Exact production destructor drain block.
        assert(wg.entries.empty() && live.empty() && deliveries.empty());
        discard_pending(&ml); // Empty repeat must not double free.
    } else {
        if (!strcmp(scenario,"no_netif")) ml.wg_netif=nullptr;
        else if (!strcmp(scenario,"no_device")) nif.state=nullptr;
        else { assert(!strcmp(scenario,"no_pbuf")); fail_pbuf=true; }
        for (bool relay:{false,true}) { send(&ml,relay); consume_one(&ml); }
        assert(live.empty() && deliveries.empty() && pbuf_live==0);
        ml.wg_netif=&nif; nif.state=&device; fail_pbuf=false;
        send(&ml,false); consume_one(&ml); // Same queue/consumer recovers.
        assert(live.empty() && deliveries.size()==1);
        release_copies();
    }
    assert(live.empty() && pbuf_live==0 && frees.size()==serial);
    for (const auto &item:frees) assert(item.second==1);
}
'''
