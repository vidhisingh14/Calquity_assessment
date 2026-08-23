"""Blocking gate: the layer-import check runs as part of the test suite.

The build spec suggests four greps run before every commit. Under deadline
pressure nobody runs them, so it runs here instead and a layer violation fails
the build.
"""

from __future__ import annotations

import subprocess
import sys


def test_no_layer_violations():
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_layers"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Layer violations detected:\n{result.stdout}\n{result.stderr}"
    )
