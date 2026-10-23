"""Compile the actual profile budgets and upstream single-core mapping."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[1]
STACK = ROOT / "microlink/components/microlink"


@pytest.mark.parametrize("no_psram", [False, True], ids=["normal", "no-psram"])
@pytest.mark.parametrize("unicore", [False, True], ids=["dual-core", "single-core"])
def test_profile_budgets(tmp_path, no_psram, unicore):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    header = (STACK / "include/microlink_internal.h").read_text()
    constants = "/*\n" + header[header.index(" * Constants\n"):header.index("/* Protocol limits */")]
    harness = tmp_path / "profiles.cpp"
    harness.write_text("#include <cassert>\n#include <cstdlib>\n" + constants + CHECKS)
    binary = tmp_path / "profiles"
    definitions = [f"-DCONFIG_FREERTOS_UNICORE={int(unicore)}"]
    if no_psram:
        definitions.append("-DCONFIG_ML_NO_PSRAM=1")
    subprocess.run([compiler, "-std=c++17", *definitions, str(harness), "-o", str(binary)], check=True)
    expected = [5120, 5632, 5632, 4608, 8, 8, 16] if no_psram else [6144, 10240, 12288, 8192, 64, 400, 32]
    subprocess.run([str(binary), *map(str, expected), str(int(unicore))], check=True, timeout=10)


CHECKS = r'''
int main(int argc, char **argv) {
    assert(argc == 9);
    const unsigned budgets[] = {ML_TASK_NET_IO_STACK, ML_TASK_DERP_TX_STACK,
        ML_TASK_COORD_STACK, ML_TASK_WG_MGR_STACK, ML_DERP_TX_QUEUE_DEPTH,
        ML_PEER_UPDATE_QUEUE_DEPTH, ML_WG_RX_QUEUE_DEPTH};
    for (unsigned i = 0; i < 7; ++i)
        assert(budgets[i] == strtoul(argv[i+1], nullptr, 10));
    const bool unicore = atoi(argv[8]);
    assert(ML_TASK_NET_IO_CORE == 0 && ML_TASK_DERP_TX_CORE == 0);
    assert(ML_TASK_COORD_CORE == (unicore ? 0 : 1));
    assert(ML_TASK_WG_MGR_CORE == (unicore ? 0 : 1));
}
'''
