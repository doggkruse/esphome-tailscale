# Endpoint contribution limitations

This contribution is reconciled against upstream `0a34e85` (v0.5.28), including
its existing no-PSRAM receive, JSON slicing, allocation fallback and packet
output. Only profile integration, fixed budgets and compact relay storage remain.
Stable IDs retain historical findings; older images do not qualify this source.

| ID | Status | Limit / evidence |
| --- | --- | --- |
| LIM-001 | Open | Full Tailscale ACL/grant enforcement remains absent. |
| LIM-002 | Open | Expiry, revocation, rotation and queued traffic need runtime qualification. |
| LIM-003 | Open | Management services need separate access protection and denied-access tests. |
| LIM-004 | Open | Custom-server trust and identity lifecycle remain outside this contribution. |
| LIM-156 | Verify | Basic local checks are in VALIDATION.md. Hosted CI and full public HTTPS component installation remain unrun. |
| LIM-157 | Historical follow-up | Broader diagnostic privacy changes remain separate; reconcile old follow-up branches with current upstream before proposing them. |
| LIM-164 | Verify | The upstream five-worker architecture remains. Initialized-PSRAM runtime comparison is unqualified. |
| LIM-166 | Addressed in scope | Custom receive/parser/output/admission implementations were removed where upstream now supplies no-PSRAM support. Routing and optional runtime policies remain separate. |
| LIM-167 | Open | Upstream per-peer map processing is retained; already-applied metadata is not rolled back on later failure. No transactional full-map protocol is added. |
| LIM-168 | Historical follow-up | Current upstream already contains lifecycle/TLS fixes. Older independent patches need reconciliation and are not established causes of measured UDP failures. |
| LIM-169 | Open | The broader hardware campaign remains incomplete. This rebase uses basic host/build checks, without hardware or performance qualification. |
| LIM-170 | Superseded by upstream | Earlier internal-only allocator experiments are preserved historically. This candidate uses upstream's no-PSRAM allocation fallback; custom allocator/output wrappers and their obsolete tests were removed. |
| LIM-187 | Open; documented | Two peer slots include idle/offline devices. Larger visible maps can exceed the buffer ceiling; increasing peers is not a capacity guarantee. |
| LIM-196 | Historical correction; current upstream behavior | Custom BEGIN/END/ABORT and deferred admission were removed during upstream reconciliation. This profile uses upstream finite queue admission and key sweep; order, queue pressure and priority-peer eviction can affect which clients remain reachable. Runtime convergence is unqualified. |
| LIM-207 | Locally checked | The normal YAML buffer range remains 64–2048 KiB. Constrained YAML/manual limits permit 16–2048 KiB; normal manual SDK settings retain upstream handling. |
| LIM-210 | Runtime unqualified | RX16/TX8/update8, reduced stacks, two peers and NVS16 bound the profile. Startup reply storage moves off the reduced coordinator stack. Actual stack headroom, transient heap and workload capacity need hardware validation. Enqueue waiting, netcheck and relay policy remain upstream. |
| LIM-242 | Source reconciled | Current upstream baseline is 0a34e85. Obsolete parallel no-PSRAM code was removed; basic regression/build checks are recorded separately. This does not close hardware findings. |

ESPHome owns PSRAM mode, speed, ECC and initialization. Profile selection follows
enabled validated `psram:` configuration, not physical detection. Installations
relying on implicit PSRAM initialization must declare it explicitly. A normal
profile with missing RAM fails Tailscale setup without changing ESPHome policy.

The profile defaults are two peers, 40 KiB H2/JSON ceilings and sixteen saved
peers. Normal defaults remain sixteen peers, 512 KiB ceilings and 64 saved peers.
Queue depths bound item counts, not payload bytes or worst-case transient RAM.
Telemetry defaults disabled without PSRAM; explicit enabling uses more memory
and is unqualified. The optional HTTP configuration server remains disabled.

Compact relay storage keeps populated hostnames/IPv4 entries and omits the
baseline's unused IPv6-literal storage. Replacement allocation failures can leave
fewer regions, including an empty map; live recovery under pressure is unqualified.

Older firmware 1fa07d8f retains its scoped successes and unresolved coordinator
continuity (LIM-222), nominal UDP loss (LIM-233), unexplained resets (LIM-234),
relay latency (LIM-235), idle API continuity (LIM-237), receive-error coverage
(LIM-239) and UDP discovery limits (LIM-240). No preexisting-cause exemption or
hardware credit transfers to this source. Full application, cold power,
initialized-PSRAM comparison, overload recovery and soak remain unqualified.
The full campaign has not passed; basic checks do not establish merge readiness.
