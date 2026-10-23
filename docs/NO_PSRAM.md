# Experimental no-PSRAM endpoint support

This contribution builds on upstream v0.5.28's no-PSRAM support with an explicit
constrained-memory profile for ESPHome WROOM endpoints. It reuses upstream
receive, JSON slicing, packet output and peer admission. It adds resource budgets
and compact relay storage, without a subnet-router option or NAT replacement.

## Configuration

```yaml
wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  power_save_mode: NONE

tailscale:
  auth_key: !secret tailscale_auth_key
  no_psram: true
```

`no_psram` defaults to `auto`. Enabled ESPHome `psram:` selects normal budgets;
absent or `disabled: true` PSRAM selects the constrained profile. ESPHome owns
PSRAM mode, speed, ECC and initialization policy; Tailscale does not force any
of them. Explicit `true` and `false` must agree with the enabled configuration.
This follows [ESPHome's PSRAM configuration](https://esphome.io/components/psram/),
not physical hardware detection. `ignore_not_found: true` still means PSRAM is
configured; if unavailable at runtime, only Tailscale fails setup rather than
silently changing its compiled profile.

The selected experimental WROOM profile uses the queue budgets below and an
explicit `wifi.power_save_mode: NONE`. Disabling Wi-Fi power saving can increase
power use. `LIGHT` and `HIGH` are not qualified for this profile. Tailscale does
not override ESPHome's Wi-Fi configuration; set this option in your own YAML.
This cleaned profile has not been qualified on hardware. Earlier firmware
results retain their own source and configuration scope.

Existing external-component installations that relied on implicit forced PSRAM
must add the correct `psram:` configuration. This deliberate migration follows
ESPHome core's explicit memory configuration and does not imply maintainer
acceptance of automatic selection in the external repository.

| Setting | PSRAM | No PSRAM |
| --- | ---: | ---: |
| Peer slots | 16 | 2 |
| Receive/JSON buffer ceiling, each | 512 KB | 40 KB |
| Buffer override range, each | 64–2048 KB | 16–2048 KB |
| Saved peers | 64 | 16 |
| WireGuard RX queue | 32 | 16 |
| WireGuard RX enqueue wait | 0 ticks | 0 ticks |
| DERP TX / peer-update queue | 64 / 400 | 8 / 8 |
| Telemetry | Upstream enabled default | Disabled by default; explicit enabling is allowed |

`max_peers` and `netmap_buffer_kb` override defaults; manual buffer/NVS SDK
settings retain precedence. These are allocation limits, not supported tailnet
sizes. The MicroLink HTTP configuration server must remain disabled.

The YAML buffer setting keeps upstream's normal 64 KB minimum and permits
16–2048 KB in the constrained profile. Added validation of manual H2/JSON SDK
limits applies only to the constrained profile; normal SDK settings retain
upstream handling. Direct and relay WireGuard RX and DISCO enqueue remain
nonblocking in both profiles, with upstream payload cleanup. Enabling telemetry
adds a task and HTTPS allocations; qualify that larger memory budget separately.
Queue depth bounds the number of retained items, not their payload bytes or
total RAM use. Worst-case packet/relay payload memory remains unqualified.

The synthetic `examples/endpoint-build.yaml` and `examples/s3-endpoint-build.yaml`
exercise no-PSRAM WROOM and PSRAM S3 respectively. Never flash their placeholder
credentials. Protect deployment API and OTA access with real secrets.

## Peer capacity and tailnet access

The no-PSRAM default `max_peers: 2` reserves state for **two other Tailscale
devices**, not two TCP connections. The ESP itself does not occupy a slot;
each installed peer can carry multiple connections and UDP flows. The PSRAM
default is 16. This is a local ESP limit: it does not restrict tailnet membership
or communication between other devices in the tailnet.

Peers are installed from the control map visible to this ESP, rather than only
when a client connects. Idle and offline installed peers still occupy slots.
Saved peers can also occupy those same slots at startup; the 16-entry no-PSRAM
saved-peer cache does not provide 16 live slots. Closing a TCP connection does
not release a peer slot.

When slots are full, a further peer can be refused with
`Peer table full (2 slots), cannot add ...`. For example, Home Assistant and a
laptop may occupy both slots and prevent a phone from accessing the ESPHome API.
Control/DERP connection status alone does not prove that a particular client
can reach the ESP. Direct and relay traffic share the same peer capacity.
The online-peer count can be lower than the occupied-slot count; it does not
prove that a slot is free. Check installation/refusal logs as well as status.

Do not rely on a particular pair being selected from a larger visible peer
set. Cached state, map order and the inherited priority-peer option affect
admission. This profile uses upstream's per-peer updates, finite queue sends
and authoritative-key sweep; it adds no transactional full-map protocol,
rollback or general on-demand slot rotation. The smaller update queue can drop
updates under pressure. Check logs and actual reachability of each required
client after startup and map changes.

The inherited priority-peer option can evict a non-priority peer and interrupt
its access. It adds no capacity and is not an allowlist or Tailscale ACL/grant
enforcement.

An explicit setting overrides the profile default, for example:

```yaml
tailscale:
  auth_key: !secret tailscale_auth_key
  max_peers: 4
```

This example illustrates configuration, not a qualified four-peer WROOM profile.
Changing it requires rebuilding firmware and increases RAM reserved for peer
and WireGuard state. The schema accepts 1–64; hardware capacity depends on the
rest of the application and must be tested under startup, reconnect and traffic
load. Verify that every required client's peer is actually installed.

The map-buffer ceiling is independent: two slots does not request a two-peer
map from the server. A larger visible map can exceed the no-PSRAM receive/JSON
buffer even if only two peers will be installed. This endpoint contribution
provides no subnet routing; a separate routing contribution must also account
for peer capacity when choosing which clients can use its advertised routes.

## Scope and validation

The contribution contains profile selection, reduced task/queue/cache budgets,
compact relay storage and a heap-based startup reply for the reduced coordinator
stack. Upstream's adaptive no-PSRAM receive, sliced JSON, allocation fallback,
WireGuard output, peer admission, relay selection and recovery are reused.
Normal-profile protocol code and budgets remain upstream. Prior custom receive,
packet-copy and full-map snapshot experiments are outside this contribution.

See [validation](VALIDATION.md) for reproducible checks and their limits, and
[limitations](LIMITATIONS_LEDGER.md) for unresolved behavior. Compilation and
host fixtures do not establish hardware reliability, supported throughput or
compatibility with an initialized PSRAM board.
