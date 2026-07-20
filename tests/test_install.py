from __future__ import annotations

import subprocess
from pathlib import Path


def test_installer_prompts_setup_and_doctor_before_first_log():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["sh", "install.sh", "--dry-run"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "nomnom setup" in result.stdout
    assert "nomnom doctor --json" in result.stdout
    assert "before the first food log" in result.stdout
