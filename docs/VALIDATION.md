# Endpoint profile validation

Use the pinned dependencies in `requirements-dev.txt` and ESP-IDF 5.5.5.
CI uses upstream Python 3.12; the local smoke check uses Python 3.14.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/run_native_checks.py
python scripts/check_public_examples.py
python scripts/check_git_install.py
esphome compile examples/endpoint-build.yaml
python scripts/check_memory_build.py --build-dir examples/.esphome/build/tailscale-wroom-endpoint --profile no-psram
python scripts/check_public_examples.py --compile-public-example
```

These checks cover the actual profile constants and single-core mapping,
nonblocking RX queue ownership, compact relay allocation/replacement, profile
configuration/code generation, and no-PSRAM/PSRAM compilation. Public example
checks use local candidate components and synthetic credentials; no upload.

## Current upstream reconciliation

The baseline is upstream `0a34e85` (v0.5.28). Its adaptive no-PSRAM receive,
Noise/H2 handling, sliced JSON, packet output, peer admission and protocol fixes
are reused. Old custom implementations and tests that only exercised those
removed paths are outside this contribution.

Basic checks passed locally on 2026-10-22:

- 16 profile/queue pytest cases and the compact-DERP ASan/UBSan fixture.
- 48 accepted configurations, 46 expected rejections, 38 code-generation cases
  and four paired comparisons with ESPHome's own PSRAM settings.
- Pinned local Git component loading and dependency-source generation.
- WROOM no-PSRAM build/profile: two peers, 40 KiB ceilings, no SPIRAM or NAPT.
- Public PSRAM example/package build/profile: sixteen peers, 512 KiB ceilings,
  SPIRAM enabled and no NAPT.

Prior counts and hardware successes remain tied to their original source.
Hosted CI and full public HTTPS installation remain unrun.

## Hardware boundary

The frozen 1fa07d8f images retain their own scoped successes and open failures.
No hardware, stress, performance or soak campaign is part of this basic rebase
check. The reduced stacks, compact storage and remaining profile budgets still
need runtime qualification, including an initialized-PSRAM comparison.
See [limitations](LIMITATIONS_LEDGER.md).
