"""Run the retained compact-DERP storage fixture with ASan/UBSan."""
from pathlib import Path
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    sources = sorted(root.glob("tests/*_test.cpp"))
    if not sources:
        raise SystemExit("No native C++ test fixtures")
    with tempfile.TemporaryDirectory(prefix="tailscale-native-") as directory:
        for source in sources:
            binary = Path(directory) / source.stem
            subprocess.run([
                "c++", "-std=c++17", "-fsanitize=address,undefined",
                "-fno-sanitize-recover=all", "-I" + str(root),
                str(source), "-o", str(binary),
            ], check=True)
            subprocess.run([str(binary)], check=True)
            print("PASS", source.name, flush=True)


if __name__ == "__main__":
    main()
