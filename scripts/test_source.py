"""Copy only component sources and synthetic build fixtures for install tests."""
from pathlib import Path
import shutil


def export_test_source(root, destination):
    root, destination = Path(root), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("components", "microlink"):
        shutil.copytree(root / name, destination / name,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "build", ".pio", ".esphome"))
    (destination / "examples").mkdir()
    for fixture in (root / "examples").glob("*-build.yaml"):
        shutil.copyfile(fixture, destination / "examples" / fixture.name)
