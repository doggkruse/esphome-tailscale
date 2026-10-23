"""Validate endpoint YAML in isolation, using only synthetic credentials."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import copy
import re
import yaml
from test_source import export_test_source


def local_yaml_value(text, key, block):
    """Replace one source field while leaving ESPHome's other YAML tags intact."""
    values = [value for name, value in yaml.compose(text, Loader=yaml.SafeLoader).value if name.value == key]
    if len(values) != 1:
        raise ValueError(f"Expected one public YAML field: {key}")
    value = values[0]
    start = value.start_mark.index - value.start_mark.column
    return (text[:start] + textwrap.indent(block, " " * value.start_mark.column) +
            "\n" + text[value.end_mark.index:])


def public_example(root, source, secrets):
    """Use this candidate's public package and components, never remote main."""
    package = source / "packages/tailscale/tailscale.yaml"
    package.parent.mkdir(parents=True)
    package_text = (root / "packages/tailscale/tailscale.yaml").read_text()
    local_component = yaml.safe_dump([
        {"source": str(source / "components"), "components": ["tailscale"]}
    ], sort_keys=False)
    package.write_text(local_yaml_value(package_text, "external_components", local_component))
    example = source / "example.yaml"
    example.write_text(local_yaml_value((root / "example.yaml").read_text(), "packages",
                       "tailscale: !include packages/tailscale/tailscale.yaml\n"))
    (source / "secrets.yaml").write_text(secrets)
    return example


def set_buffer_size(config, key, value):
    if key == "netmap_buffer_kb":
        config["tailscale"][key] = value
    else:
        options = config["esp32"]["framework"].setdefault("sdkconfig_options", {})
        options[key] = str(value)


def check_codegen(source, examples, name, generated, expected_values):
    """Check actual sdkconfig and C++ after the complete schema lifecycle."""
    generated = copy.deepcopy(generated)
    node = f"ml-{name}"
    generated["esphome"]["name"] = node
    fixture = examples / f"generate-profile-{name}.yaml"
    fixture.write_text(yaml.safe_dump(generated))
    result = subprocess.run(
        [sys.executable, "-m", "esphome", "compile", "--only-generate", str(fixture)],
        cwd=source, capture_output=True, text=True, timeout=120,
    )
    if result.returncode:
        print(f"FAIL memory profile codegen {name}\n{result.stdout}\n{result.stderr}", file=sys.stderr)
        return False
    build = examples / ".esphome" / "build" / node
    lines = set((build / f"sdkconfig.{node}.esphomeinternal").read_text().splitlines())
    for key, value in expected_values.items():
        matches = [line for line in lines if line.startswith(f"{key}=")]
        if (value is None and matches) or (value is not None and matches != [f"{key}={value}"]):
            print(f"FAIL memory profile codegen {name}: {key} expected {value}, got {matches}", file=sys.stderr)
            return False
    generated_cpp = (build / "src/main.cpp").read_text()
    if f"->set_max_peers({expected_values['CONFIG_ML_MAX_PEERS']});" not in generated_cpp:
        print(f"FAIL runtime peer capacity: {name}", file=sys.stderr)
        return False
    no_psram = expected_values["CONFIG_ML_NO_PSRAM"] == "y"
    telemetry_disabled = generated["tailscale"].get("disable_telemetry", no_psram)
    call = f"->set_telemetry_disabled({str(telemetry_disabled).lower()});"
    if call not in generated_cpp:
        print(f"FAIL telemetry profile default: {name}; expected {call}", file=sys.stderr)
        return False
    if "->set_relay_enabled(" in generated_cpp or "->set_force_relay(" in generated_cpp:
        print(f"FAIL unrelated relay controls in memory profile: {name}", file=sys.stderr)
        return False
    print(f"PASS memory profile codegen {name}", flush=True)
    return True


def check_core_psram_codegen(source, examples, name, generated, expected):
    """Compare ESPHome's real PSRAM options with and without Tailscale.

    The reference build uses the same board, psram settings and other ESPHome
    components. Only tailscale is removed, so this checks component ownership
    against ESPHome codegen rather than reimplementing its defaults in a fake.
    """
    snapshots = {}
    for enabled in (False, True):
        config = copy.deepcopy(generated)
        node = f"ml-core-{name}-{int(enabled)}"
        config["esphome"]["name"] = node
        if not enabled:
            config.pop("tailscale", None)
        fixture = examples / f"{node}.yaml"
        fixture.write_text(yaml.safe_dump(config))
        result = subprocess.run(
            [sys.executable, "-m", "esphome", "compile", "--only-generate", str(fixture)],
            cwd=source, capture_output=True, text=True, timeout=120,
        )
        if result.returncode:
            print(f"FAIL ESPHome PSRAM comparison {node}\n{result.stdout}\n{result.stderr}", file=sys.stderr)
            return False
        build = examples / ".esphome" / "build" / node
        options = {}
        for line in (build / f"sdkconfig.{node}.esphomeinternal").read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and (key.startswith("CONFIG_SPIRAM") or key == "CONFIG_SOC_SPIRAM_SUPPORTED"):
                # This flag permits external task stacks; it does not select
                # hardware, change PSRAM initialization, or move any task.
                if key != "CONFIG_SPIRAM_ALLOW_STACK_EXTERNAL_MEMORY":
                    options[key] = value
        snapshots[enabled] = options
        main = (build / "src/main.cpp").read_text()
        if ("->set_auth_key(" in main) != enabled:
            print(f"FAIL ESPHome PSRAM reference isolation: {node}", file=sys.stderr)
            return False
    if snapshots[False] != snapshots[True]:
        print(f"FAIL ESPHome PSRAM settings changed for {name}: "
              f"core={snapshots[False]}, tailscale={snapshots[True]}", file=sys.stderr)
        return False
    # Avoid a vacuous match: prove the core reference exercised the intended
    # enabled, mode, speed, missing-memory and ECC settings.
    for key, value in expected.items():
        if snapshots[False].get(key) != value:
            print(f"FAIL ESPHome PSRAM reference {name}: {key} expected {value}, "
                  f"got {snapshots[False].get(key)}", file=sys.stderr)
            return False
    print(f"PASS ESPHome core PSRAM comparison {name}: {snapshots[False]}", flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile-public-example", action="store_true",
                        help="Compile and check the public PSRAM example using only local candidate sources")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="tailscale-public-yaml-") as temp:
        source = Path(temp) / "source"
        export_test_source(root, source)
        examples = source / "examples"
        secrets = (
            'wifi_ssid: compile-only-network\n'
            'wifi_password: compile-only-password\n'
            'tailscale_auth_key: compile-only-not-an-auth-key\n'
            'api_encryption_key: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n'
            'ota_password: compile-only-ota-password\n'
        )
        (examples / "secrets.yaml").write_text(secrets)
        example = public_example(root, source, secrets)
        if args.compile_public_example:
            subprocess.run([sys.executable, "-m", "esphome", "compile", str(example)],
                           cwd=source, check=True, timeout=1800)
            # The public S3 example is the normal-profile build in CI.
            node = yaml.compose(example.read_text(), Loader=yaml.SafeLoader)
            esphome = next(value for key, value in node.value if key.value == "esphome")
            name = next(value.value for key, value in esphome.value if key.value == "name")
            subprocess.run([sys.executable, str(root / "scripts/check_memory_build.py"),
                            "--build-dir", str(source / ".esphome/build" / name),
                            "--profile", "psram"], check=True)
            print("PASS public example/package compiled from local candidate sources; no upload")
            return 0
        fixtures = [example, examples / "endpoint-build.yaml", examples / "s3-endpoint-build.yaml"]
        base = yaml.safe_load((examples / "endpoint-build.yaml").read_text())
        psram_base = yaml.safe_load((examples / "s3-endpoint-build.yaml").read_text())
        keys = ("CONFIG_ML_H2_BUFFER_SIZE_KB", "CONFIG_ML_JSON_BUFFER_SIZE_KB")
        buffer_targets = (("netmap", "netmap_buffer_kb"), ("h2", keys[0]), ("json", keys[1]))
        buffer_rejections = []
        for name, profile_base, spiram in (
            ("no-psram-manual-disabled", base, "n"),
            ("psram-manual-enabled", psram_base, "y"),
        ):
            accepted = copy.deepcopy(profile_base)
            accepted["esp32"]["framework"].setdefault("sdkconfig_options", {})["CONFIG_SPIRAM"] = spiram
            fixture = examples / f"valid-{name}.yaml"
            fixture.write_text(yaml.safe_dump(accepted))
            fixtures.append(fixture)
        # Check all three public configuration paths independently. In
        # particular, raw SDK overrides must not bypass the resolved profile.
        for profile, profile_base, sizes in (
            ("no-psram", base, (16, 40, 63, 128, 2048)),
            ("psram", psram_base, (64, 2048)),
        ):
            for target, key in buffer_targets:
                for size in sizes:
                    accepted = copy.deepcopy(profile_base)
                    set_buffer_size(accepted, key, size)
                    fixture = examples / f"valid-buffer-{profile}-{target}-{size}.yaml"
                    fixture.write_text(yaml.safe_dump(accepted))
                    fixtures.append(fixture)
        for target, key in buffer_targets[:1]:
            for size in (16, 40, 63):
                invalid = copy.deepcopy(psram_base)
                set_buffer_size(invalid, key, size)
                buffer_rejections.append((f"psram-{target}-{size}", invalid,
                                          f"{key} must be between 64 and 2048 KiB"))
        for profile, profile_base, minimum, sizes in (
            ("no-psram", base, 16, (15, 2049)),
        ):
            for target, key in buffer_targets[1:]:
                for size in sizes:
                    invalid = copy.deepcopy(profile_base)
                    set_buffer_size(invalid, key, size)
                    buffer_rejections.append((f"{profile}-{target}-{size}", invalid,
                                              f"{key} must be between {minimum} and 2048 KiB"))
        for target, key in buffer_targets[1:]:
            for label, value in (
                ("bool", "n"), ("fraction", "16.5"), ("hex", "0x40"), ("empty", ""),
                ("leading-zero", "064"), ("underscore", "6_4"), ("unicode", "\uff16\uff14"),
                ("signed-plus", "+64"), ("signed-minus", "-64"),
                ("leading-space", " 64"), ("trailing-space", "64 "),
            ):
                invalid = copy.deepcopy(base)
                set_buffer_size(invalid, key, value)
                buffer_rejections.append((f"sdk-{target}-{label}", invalid,
                                          f"{key} must be a decimal integer"))
            invalid = copy.deepcopy(base)
            invalid["tailscale"]["netmap_buffer_kb"] = 128
            set_buffer_size(invalid, key, 15)
            buffer_rejections.append((f"sdk-{target}-overrides-shared", invalid,
                                      f"{key} must be between 16 and 2048 KiB"))
        invalid = copy.deepcopy(psram_base)
        invalid["tailscale"]["netmap_buffer_kb"] = 63
        for key in keys:
            set_buffer_size(invalid, key, 128)
        buffer_rejections.append(("invalid-shared-with-valid-sdk", invalid,
                                  "netmap_buffer_kb must be between 64 and 2048 KiB"))
        # Use real ESPHome final validation and codegen: memory availability
        # follows the validated PSRAM component, including packages and string
        # booleans, rather than a chip-name guess or raw YAML truthiness.
        memory_fixtures = []
        for name, profile_base, selection, psram_state, expected_no_psram in (
            ("omitted-wroom", base, None, "absent", True),
            ("auto-wroom", base, "auto", "absent", True),
            ("true-wroom", base, True, "absent", True),
            ("omitted-s3-psram", psram_base, None, "enabled", False),
            ("auto-s3-psram", psram_base, "auto", "enabled", False),
            ("false-s3-psram", psram_base, False, "enabled", False),
            ("auto-s3-no-psram", psram_base, "auto", "absent", True),
            ("omitted-s3-disabled", psram_base, None, "disabled", True),
            ("auto-s3-disabled", psram_base, "auto", "disabled", True),
            ("true-s3-disabled", psram_base, True, "disabled", True),
            ("false-s3-enabled", psram_base, False, "disabled-false", False),
            ("auto-s3-string-false", psram_base, "auto", "disabled-string-false", False),
            ("auto-classic-quad", base, "auto", "quad", False),
            ("auto-package-psram", psram_base, "auto", "package", False),
            ("auto-package-disabled", psram_base, "auto", "package-disabled", True),
            ("omitted-package-psram", psram_base, None, "package", False),
        ):
            accepted = copy.deepcopy(profile_base)
            accepted["tailscale"].pop("max_peers", None)
            accepted["tailscale"].pop("disable_telemetry", None)
            accepted["tailscale"].pop("no_psram", None)
            if selection is not None:
                accepted["tailscale"]["no_psram"] = selection
            if psram_state == "absent":
                accepted.pop("psram", None)
            elif psram_state == "disabled":
                accepted["psram"]["disabled"] = True
            elif psram_state == "disabled-false":
                accepted["psram"]["disabled"] = False
            elif psram_state == "disabled-string-false":
                accepted["psram"]["disabled"] = "false"
            elif psram_state == "quad":
                accepted["psram"] = {"mode": "quad", "speed": "40MHz"}
            elif psram_state.startswith("package"):
                psram = accepted.pop("psram")
                if psram_state == "package-disabled":
                    psram["disabled"] = True
                accepted["packages"] = {"memory": {"psram": psram}}
            fixture = examples / f"valid-profile-{name}.yaml"
            fixture.write_text(yaml.safe_dump(accepted))
            fixtures.append(fixture)
            memory_fixtures.append((name, accepted, expected_no_psram))
        for name, profile_base, no_psram in memory_fixtures:
            if name not in ("auto-package-psram", "auto-package-disabled",
                            "auto-s3-string-false", "auto-s3-disabled"):
                continue
            for target, key in buffer_targets:
                candidate = copy.deepcopy(profile_base)
                set_buffer_size(candidate, key, 16 if no_psram else 63)
                case_name = f"{name}-{target}-minimum"
                if no_psram:
                    fixture = examples / f"valid-{case_name}.yaml"
                    fixture.write_text(yaml.safe_dump(candidate))
                    fixtures.append(fixture)
                elif key == "netmap_buffer_kb":
                    buffer_rejections.append((case_name, candidate,
                                              f"{key} must be between 64 and 2048 KiB"))
        for fixture in fixtures:
            result = subprocess.run(
                [sys.executable, "-m", "esphome", "config", str(fixture)],
                cwd=source, capture_output=True, text=True, timeout=120,
            )
            if result.returncode:
                print(f"FAIL {fixture.name}", file=sys.stderr)
                # This tree contains only publication files and synthetic secrets.
                print(result.stderr, file=sys.stderr)
                print(result.stdout, file=sys.stderr)
                return result.returncode
            print(f"PASS {fixture.name}", flush=True)
        cases = list(buffer_rejections)
        for name, profile_base, spiram, expected in (
            ("no-psram-manual-enabled", base, "y", "CONFIG_SPIRAM must be 'n'"),
            ("psram-manual-disabled", psram_base, "n", "CONFIG_SPIRAM must be 'y'"),
        ):
            invalid = copy.deepcopy(profile_base)
            invalid["esp32"]["framework"].setdefault("sdkconfig_options", {})["CONFIG_SPIRAM"] = spiram
            cases.append((name, invalid, expected))
        missing_psram = copy.deepcopy(psram_base)
        missing_psram.pop("psram", None)
        missing_psram["tailscale"]["no_psram"] = False
        cases.append(("missing-psram", missing_psram, "no_psram: false requires an enabled 'psram:' component"))
        contradictory_psram = copy.deepcopy(psram_base)
        contradictory_psram["tailscale"]["no_psram"] = True
        cases.append(("contradictory-psram", contradictory_psram, "cannot be combined with an enabled 'psram:' component"))
        for name, disabled, no_psram, expected in (
            ("disabled-psram-false-profile", True, False, "no_psram: false requires an enabled 'psram:' component"),
            ("enabled-psram-true-profile", False, True, "cannot be combined with an enabled 'psram:' component"),
            ("string-enabled-psram-true-profile", "false", True, "cannot be combined with an enabled 'psram:' component"),
        ):
            invalid = copy.deepcopy(psram_base)
            invalid["psram"]["disabled"] = disabled
            invalid["tailscale"]["no_psram"] = no_psram
            cases.append((name, invalid, expected))
        package_conflict = copy.deepcopy(psram_base)
        package_conflict["packages"] = {"memory": {"psram": package_conflict.pop("psram")}}
        package_conflict["tailscale"]["no_psram"] = True
        cases.append(("package-psram-true-profile", package_conflict, "cannot be combined with an enabled 'psram:' component"))
        manual_profile = copy.deepcopy(base)
        manual_profile["esp32"]["framework"].setdefault("sdkconfig_options", {})["CONFIG_ML_NO_PSRAM"] = "n"
        cases.append(("manual-memory-profile", manual_profile, "controlled by tailscale.no_psram"))
        missing_network = copy.deepcopy(base)
        for component in ("wifi", "api", "ota", "time"):
            missing_network.pop(component, None)
        cases.append(("missing-network", missing_network, "requires either 'wifi:' or 'ethernet:'"))
        for size in (15, 2049):
            invalid = copy.deepcopy(base)
            invalid["tailscale"]["netmap_buffer_kb"] = size
            cases.append((f"netmap-range-{size}", invalid,
                          "at least 16" if size == 15 else "at most 2048"))
        for name, invalid, expected in cases:
            fixture = examples / f"invalid-{name}.yaml"
            fixture.write_text(yaml.safe_dump(invalid))
            result = subprocess.run(
                [sys.executable, "-m", "esphome", "config", str(fixture)],
                cwd=source, capture_output=True, text=True, timeout=120,
            )
            output = result.stdout + result.stderr
            if result.returncode == 0 or expected not in output or "Traceback" in output:
                print(f"FAIL expected schema rejection: {name}\n{output}", file=sys.stderr)
                return 1
            print(f"PASS rejects {name}", flush=True)
        # Exercise both profiles through actual ESPHome codegen. Normal PSRAM
        # defaults must remain unmodified; manual options take precedence over
        # both profile defaults and the shared netmap knob, independently.
        nvs_key = "CONFIG_ML_NVS_MAX_PEERS"
        kconfig = (source / "microlink/components/microlink/Kconfig").read_text()
        for name, expected in (("ML_H2_BUFFER_SIZE_KB", 512), ("ML_JSON_BUFFER_SIZE_KB", 512), ("ML_NVS_MAX_PEERS", 64)):
            block = re.search(rf"(?m)^    config {name}\n(?P<body>.*?)(?=^    (?:config|menu)|\Z)", kconfig, re.S)
            if block is None or not re.search(rf"(?m)^        default {expected}$", block["body"]):
                print(f"FAIL upstream Kconfig default: {name}={expected}", file=sys.stderr)
                return 1
        codegen_count = 0
        for profile, profile_base, default_size, default_nvs, default_peers in (
            ("psram", psram_base, None, None, 16),
            ("no-psram", base, 40, 16, 2),
        ):
            minimum = 16 if profile == "no-psram" else 64
            for case, size, manual, expected, explicit_peers in (
                ("default", None, {}, (default_size, default_size, default_nvs), None),
                ("explicit", 128, {}, (128, 128, default_nvs), 7),
                ("manual", None, {keys[0]: 80, keys[1]: 96, nvs_key: 32}, (80, 96, 32), None),
                ("manual-explicit", 128, {keys[0]: 80, keys[1]: 96, nvs_key: 32}, (80, 96, 32), None),
                ("mixed-manual", 128, {keys[0]: 80}, (80, 128, default_nvs), None),
                ("minimum", minimum, {}, (minimum, minimum, default_nvs), None),
                ("manual-minimum", 128, {keys[0]: minimum, keys[1]: minimum},
                 (minimum, minimum, default_nvs), None),
                ("maximum", 2048, {}, (2048, 2048, default_nvs), None),
                ("manual-maximum", 128, {keys[0]: 2048, keys[1]: 2048},
                 (2048, 2048, default_nvs), None),
            ):
                name = f"{profile}-{case}"
                generated = copy.deepcopy(profile_base)
                generated["tailscale"].pop("max_peers", None)
                generated["tailscale"].pop("disable_telemetry", None)
                generated["tailscale"].pop("no_psram", None)
                generated["tailscale"].pop("netmap_buffer_kb", None)
                if explicit_peers is not None:
                    generated["tailscale"]["max_peers"] = explicit_peers
                if size is not None:
                    generated["tailscale"]["netmap_buffer_kb"] = size
                options = generated["esp32"]["framework"].setdefault("sdkconfig_options", {})
                for key in (*keys, nvs_key):
                    options.pop(key, None)
                options.update({key: str(value) for key, value in manual.items()})
                expected_values = dict(zip((*keys, nvs_key), expected))
                expected_values["CONFIG_ML_MAX_PEERS"] = explicit_peers or default_peers
                expected_values["CONFIG_ML_NO_PSRAM"] = "y" if profile == "no-psram" else "n"
                expected_values["CONFIG_LWIP_IP_FORWARD"] = "n" if profile == "no-psram" else "y"
                if not check_codegen(source, examples, name, generated, expected_values):
                    return 1
                codegen_count += 1
        for name, generated, no_psram in memory_fixtures:
            expected_values = {
                keys[0]: 40 if no_psram else None,
                keys[1]: 40 if no_psram else None,
                nvs_key: 16 if no_psram else None,
                "CONFIG_ML_MAX_PEERS": 2 if no_psram else 16,
                "CONFIG_ML_NO_PSRAM": "y" if no_psram else "n",
                "CONFIG_SPIRAM": None if no_psram else "y",
                "CONFIG_LWIP_IP_FORWARD": "n" if no_psram else "y",
            }
            if not check_codegen(source, examples, name, generated, expected_values):
                return 1
            codegen_count += 1
        # Upstream now supports telemetry on the default heap in both profiles.
        # The constrained default omits it, while explicit choices remain valid.
        for profile, profile_base, no_psram in (
            ("psram", psram_base, False), ("no-psram", base, True),
        ):
            for disabled in (False, True):
                generated = copy.deepcopy(profile_base)
                generated["tailscale"]["disable_telemetry"] = disabled
                expected_values = {
                    keys[0]: 40 if no_psram else None,
                    keys[1]: 40 if no_psram else None,
                    nvs_key: 16 if no_psram else None,
                    "CONFIG_ML_MAX_PEERS": 2 if no_psram else 16,
                    "CONFIG_ML_NO_PSRAM": "y" if no_psram else "n",
                    "CONFIG_LWIP_IP_FORWARD": "n" if no_psram else "y",
                }
                if not check_codegen(source, examples, f"{profile}-telemetry-{int(disabled)}", generated, expected_values):
                    return 1
                codegen_count += 1
        core_comparisons = 0
        for name, profile_base, psram_options, expected in (
            ("classic", base, {}, {
                "CONFIG_SPIRAM": "y", "CONFIG_SPIRAM_MODE_QUAD": "y",
                "CONFIG_SPIRAM_SPEED_40M": "y", "CONFIG_SPIRAM_SPEED": "40",
                "CONFIG_SPIRAM_IGNORE_NOTFOUND": "y", "CONFIG_SPIRAM_ECC_ENABLE": None,
            }),
            ("s3-strict", psram_base, {
                "mode": "octal", "speed": "80MHz", "ignore_not_found": False,
            }, {
                "CONFIG_SPIRAM": "y", "CONFIG_SPIRAM_MODE_OCT": "y",
                "CONFIG_SPIRAM_SPEED_80M": "y", "CONFIG_SPIRAM_SPEED": "80",
                "CONFIG_SPIRAM_IGNORE_NOTFOUND": "n", "CONFIG_SPIRAM_ECC_ENABLE": None,
            }),
            ("s3-ecc", psram_base, {
                "mode": "octal", "speed": "80MHz", "ignore_not_found": False,
                "enable_ecc": True,
            }, {
                "CONFIG_SPIRAM": "y", "CONFIG_SPIRAM_MODE_OCT": "y",
                "CONFIG_SPIRAM_SPEED_80M": "y", "CONFIG_SPIRAM_SPEED": "80",
                "CONFIG_SPIRAM_IGNORE_NOTFOUND": "n", "CONFIG_SPIRAM_ECC_ENABLE": "y",
            }),
            ("disabled", psram_base, {
                "mode": "octal", "speed": "80MHz", "disabled": True,
            }, {
                "CONFIG_SPIRAM": None, "CONFIG_SPIRAM_MODE_OCT": None,
                "CONFIG_SPIRAM_SPEED_80M": None, "CONFIG_SPIRAM_SPEED": None,
                "CONFIG_SPIRAM_IGNORE_NOTFOUND": None, "CONFIG_SPIRAM_ECC_ENABLE": None,
            }),
        ):
            generated = copy.deepcopy(profile_base)
            generated["psram"] = psram_options
            generated["tailscale"].pop("no_psram", None)
            generated["tailscale"].pop("max_peers", None)
            if not check_core_psram_codegen(source, examples, name, generated, expected):
                return 1
            core_comparisons += 1
        print(f"Validated {len(fixtures)} public configurations and {len(cases)} expected rejections plus {codegen_count} memory-profile codegen cases and {core_comparisons} ESPHome core PSRAM comparisons (2 generations each); no firmware compile or upload.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
