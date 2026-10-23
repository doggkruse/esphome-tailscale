"""Check memory-profile defaults in completed synthetic endpoint builds."""
import argparse
import json
from pathlib import Path
import re


def check_build(project, profile):
    project = Path(project).resolve()
    if (project / "config/sdkconfig.h").is_file():
        project = project.parent
    build = project / "build"
    if not (build / "firmware.elf").is_file():
        raise ValueError("Compile the firmware first; generated source is insufficient")
    settings = dict(re.findall(r"^#define\s+(CONFIG_\w+)\s+(\S+)\s*$",
                              (build / "config/sdkconfig.h").read_text(), re.M))
    constrained = profile == "no-psram"
    expected = {
        "CONFIG_SPIRAM": None if constrained else "1",
        "CONFIG_ML_NO_PSRAM": "1" if constrained else None,
        "CONFIG_ML_MAX_PEERS": "2" if constrained else "16",
        "CONFIG_ML_NVS_MAX_PEERS": "16" if constrained else "64",
        "CONFIG_ML_H2_BUFFER_SIZE_KB": "40" if constrained else "512",
        "CONFIG_ML_JSON_BUFFER_SIZE_KB": "40" if constrained else "512",
        "CONFIG_LWIP_IPV4_NAPT": None,
        # Preserve upstream PSRAM configuration. This alone installs no router.
        "CONFIG_LWIP_IP_FORWARD": None if constrained else "1",
    }
    for key, value in expected.items():
        if settings.get(key) != value:
            raise ValueError(f"{key}: expected {value!r}, found {settings.get(key)!r}")
    source = re.sub(r"//[^\n]*|/\*.*?\*/", "", (project / "src/main.cpp").read_text(), flags=re.S)
    peers = re.findall(r"->set_max_peers\((\d+)\);", source)
    if peers != [expected["CONFIG_ML_MAX_PEERS"]]:
        raise ValueError("Generated runtime peer capacity differs from memory profile")
    if "USE_TAILSCALE_ROUTER" in (project / "src/esphome/core/defines.h").read_text():
        raise ValueError("Endpoint unexpectedly contains routing integration")
    link = (build / "build.ninja").read_text()
    if any(f"--wrap={name}" in link for name in ("ip4_input", "ip_napt_recv", "ip_napt_forward", "ip4_route_src_hook")):
        raise ValueError("Endpoint unexpectedly installs routing hooks")
    return {"profile": profile, "settings": expected}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--profile", required=True, choices=("psram", "no-psram"))
    args = parser.parse_args()
    print("PASS memory build:", json.dumps(check_build(args.build_dir, args.profile), sort_keys=True))
