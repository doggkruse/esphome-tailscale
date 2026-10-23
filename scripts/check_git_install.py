"""Exercise ESPHome Git loading with a temporary synthetic repository; never push."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import yaml
from test_source import export_test_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full-build", action="store_true",
        help="Also compile the isolated synthetic firmware (uses the normal ESPHome SDK cache)",
    )
    parser.add_argument("--fixture", help="Compile-only example name, without .yaml")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="tailscale-git-check-") as temp:
        parent = Path(temp)
        repo = parent / "repository"
        export_test_source(root, repo)

        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()

        git("init", "-q")
        git("add", "--all")
        git("-c", "user.name=Publication Test Fixture", "-c",
            "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
            "commit", "-qm", "Synthetic local publication fixture")
        revision = git("rev-parse", "HEAD")
        consumer = parent / "consumer"
        consumer.mkdir()
        fixture_name = args.fixture or "endpoint-build"
        if Path(fixture_name).name != fixture_name or not fixture_name.endswith("-build"):
            parser.error("--fixture must name a compile-only *-build example")
        fixture = (repo / "examples" / f"{fixture_name}.yaml").read_text()
        original = yaml.safe_load(fixture)
        marker = "  - source: ../components"
        if fixture.count(marker) != 1:
            raise RuntimeError("Update Git installation test for changed fixture source layout")
        fixture = fixture.replace(marker,
            f"  - source:\n      type: git\n      url: {repo.as_uri()}\n"
            f"      ref: {revision}\n    components: [tailscale]")
        config = consumer / "device.yaml"
        config.write_text(fixture)
        result = subprocess.run([sys.executable, "-m", "esphome", "compile",
                                 "--only-generate", str(config)],
                                capture_output=True, text=True, timeout=180)
        if result.returncode:
            print(result.stdout + result.stderr, file=sys.stderr)
            return result.returncode
        build = consumer / ".esphome/build" / original["esphome"]["name"]
        manifest = yaml.safe_load((build / "src/idf_component.yml").read_text())
        cache = (consumer / ".esphome/external_components").resolve()
        dependencies = ["microlink", "wireguard_lwip"]
        if "tailscale_napt" in manifest["dependencies"]:
            raise RuntimeError("Endpoint unexpectedly pulls in the NAPT replacement")
        for name in dependencies:
            dependency = Path(manifest["dependencies"][name]["path"]).resolve()
            if not dependency.is_relative_to(cache) or not (dependency / "CMakeLists.txt").is_file():
                raise RuntimeError(f"{name} does not resolve to a complete cloned dependency")
            resolved_revision = subprocess.run(
                ["git", "-C", str(dependency), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            if resolved_revision != revision:
                raise RuntimeError(f"{name} does not resolve to the pinned publication revision")
        print(f"PASS pinned local Git loading and cloned IDF dependency generation: {revision}", flush=True)
        if args.full_build:
            print(f"Compiling isolated synthetic Git consumer with {sys.executable}", flush=True)
            result = subprocess.run(
                [sys.executable, "-m", "esphome", "compile", str(config)],
                timeout=1800,
            )
            if result.returncode:
                return result.returncode
            psram = original.get("psram")
            profile = "psram" if psram is not None and not psram.get("disabled", False) else "no-psram"
            subprocess.run([
                sys.executable, str(root / "scripts/check_memory_build.py"),
                "--build-dir", str(build), "--profile", profile,
            ], check=True)
            print("PASS full isolated Git-consumer firmware build; no upload")
        else:
            print("Source generation only; use --full-build to also compile firmware. No upload.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
