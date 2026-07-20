from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "git+https://github.com/maxjustships/nomnomcli"


def _executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _nomnom_fixture(tmp_path: Path, *, usda_ready: bool = False) -> Path:
    doctor_payload = json.dumps(
        {
            "providers": {
                "openfoodfacts": {
                    "configured": True,
                    "product_lookup_reachable": True,
                    "full_text_search_ready": True,
                },
                "usda": {
                    "configured": usda_ready,
                    "reachable": usda_ready,
                    "key_source": None,
                },
            }
        },
        separators=(",", ":"),
    )
    return _executable(
        tmp_path / "nomnom-fixture",
        f"""#!/bin/sh
printf 'nomnom %s\\n' "$*" >> "$TRACE"
if [ -n "${{VIRTUAL_ENV:-}}" ] || [ -n "${{PYTHONPATH:-}}" ] || [ -n "${{PYTHONHOME:-}}" ]; then
  printf '%s\\n' 'private Python environment leaked into verification' >&2
  exit 90
fi
case "$*" in
  "--version") printf '%s\\n' 'nomnom 0.4.0' ;;
  "doctor --json")
    printf '%s\\n' {json.dumps(doctor_payload)}
    ;;
  *) exit 2 ;;
esac
""",
    )


def _base_environment(tmp_path: Path, harness_bin: Path, nomnom_fixture: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "trace.log"
    database = tmp_path / "existing.sqlite3"
    database.write_bytes(b"existing-user-database-must-not-change")
    return {
        "HOME": str(home),
        "PATH": f"{harness_bin}:/usr/bin:/bin",
        "SHELL": "/bin/sh",
        "TRACE": str(trace),
        "FAKE_NOMNOM": str(nomnom_fixture),
        "NOMNOM_DB_PATH": str(database),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }


def _run_installer(environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/bin/sh", "install.sh", *arguments],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("usda_ready", "expected_status"),
    [
        (False, "installed_needs_provider_setup"),
        (True, "installed_and_ready"),
    ],
)
def test_installer_prefers_uv_and_reports_provider_state_without_network(
    tmp_path, usda_ready, expected_status
):
    harness_bin = tmp_path / "harness-bin"
    tool_bin = tmp_path / "home" / ".local" / "bin"
    fixture = _nomnom_fixture(tmp_path, usda_ready=usda_ready)
    environment = _base_environment(tmp_path, harness_bin, fixture)
    environment["UV_TOOL_BIN_DIR"] = str(tool_bin)
    Path(environment["HOME"], ".profile").write_text(
        'PATH="$HOME/.local/bin:$PATH"\nexport PATH\n', encoding="utf-8"
    )
    _executable(
        harness_bin / "uv",
        """#!/bin/sh
printf 'uv %s\n' "$*" >> "$TRACE"
if [ "$1 $2 $3" = "tool install --force" ]; then
  mkdir -p "$UV_TOOL_BIN_DIR"
  cp "$FAKE_NOMNOM" "$UV_TOOL_BIN_DIR/nomnom"
  exit 0
fi
if [ "$1 $2 $3" = "tool dir --bin" ]; then
  printf '%s\n' "$UV_TOOL_BIN_DIR"
  exit 0
fi
exit 2
""",
    )
    _executable(
        harness_bin / "pipx",
        """#!/bin/sh
printf 'pipx %s\n' "$*" >> "$TRACE"
exit 99
""",
    )

    before = Path(environment["NOMNOM_DB_PATH"]).read_bytes()
    result = _run_installer(environment, "--status-json")
    after = Path(environment["NOMNOM_DB_PATH"]).read_bytes()

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "status": expected_status,
        "executable": str(tool_bin / "nomnom"),
        "version": "nomnom 0.4.0",
        "error": None,
        "path_repair": None,
    }
    trace = Path(environment["TRACE"]).read_text(encoding="utf-8")
    assert f"uv tool install --force {REPO_URL}" in trace
    assert "pipx " not in trace
    assert "nomnom --version" in trace
    assert "nomnom doctor --json" in trace
    assert before == after


def test_installer_uses_pipx_when_uv_is_unavailable(tmp_path):
    harness_bin = tmp_path / "harness-bin"
    tool_bin = tmp_path / "pipx-bin"
    fixture = _nomnom_fixture(tmp_path, usda_ready=True)
    environment = _base_environment(tmp_path, harness_bin, fixture)
    environment["PIPX_BIN_DIR"] = str(tool_bin)
    _executable(
        harness_bin / "pipx",
        """#!/bin/sh
printf 'pipx %s\n' "$*" >> "$TRACE"
if [ "$1 $2 $3" = "install --force git+https://github.com/maxjustships/nomnomcli" ]; then
  mkdir -p "$PIPX_BIN_DIR"
  cp "$FAKE_NOMNOM" "$PIPX_BIN_DIR/nomnom"
  exit 0
fi
if [ "$1 $2 $3" = "environment --value PIPX_BIN_DIR" ]; then
  printf '%s\n' "$PIPX_BIN_DIR"
  exit 0
fi
exit 2
""",
    )

    result = _run_installer(environment, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "installed_path_repair_needed"
    assert payload["executable"] == str(tool_bin / "nomnom")
    assert payload["version"] == "nomnom 0.4.0"
    assert f'export PATH="{tool_bin}:$PATH"' in payload["path_repair"]
    assert payload["error"] is None
    assert f"pipx install --force {REPO_URL}" in Path(environment["TRACE"]).read_text()


def test_installer_user_site_fallback_skips_agent_venv_python(tmp_path):
    agent_bin = tmp_path / "agent-venv" / "bin"
    system_bin = tmp_path / "system-bin"
    tool_bin = tmp_path / "home" / ".local" / "bin"
    fixture = _nomnom_fixture(tmp_path, usda_ready=True)
    environment = _base_environment(tmp_path, system_bin, fixture)
    environment["PATH"] = f"{agent_bin}:{system_bin}:/usr/bin:/bin"
    environment["VIRTUAL_ENV"] = str(agent_bin.parent)
    _executable(
        agent_bin / "python3",
        """#!/bin/sh
printf 'agent-python %s\n' "$*" >> "$TRACE"
exit 0
""",
    )
    _executable(
        system_bin / "python3.11",
        """#!/bin/sh
printf 'system-python %s\n' "$*" >> "$TRACE"
if [ "$1" = "-c" ]; then
  case "$2" in
    *sysconfig*) printf '%s\n' "$HOME/.local/bin" ;;
    *sys.executable*) printf '%s\n' "$0" ;;
  esac
  exit 0
fi
if [ "$1 $2" = "-m pip" ]; then
  mkdir -p "$HOME/.local/bin"
  cp "$FAKE_NOMNOM" "$HOME/.local/bin/nomnom"
  exit 0
fi
exit 2
""",
    )

    result = _run_installer(environment, "--status-json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["executable"] == str(tool_bin / "nomnom")
    trace = Path(environment["TRACE"]).read_text(encoding="utf-8")
    assert "agent-python -m pip" not in trace
    assert f"system-python -m pip install --user --upgrade {REPO_URL}" in trace


def test_installer_venv_only_fallback_is_actionable_structured_error(tmp_path):
    agent_bin = tmp_path / "agent-venv" / "bin"
    utilities = tmp_path / "utilities"
    utilities.mkdir()
    for name in ("awk", "env"):
        os.symlink(Path("/usr/bin") / name, utilities / name)
    fixture = _nomnom_fixture(tmp_path)
    environment = _base_environment(tmp_path, utilities, fixture)
    environment["PATH"] = f"{agent_bin}:{utilities}"
    environment["VIRTUAL_ENV"] = str(agent_bin.parent)
    _executable(agent_bin / "python3", "#!/bin/sh\nexit 0\n")

    result = _run_installer(environment, "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["executable"] is None
    assert payload["version"] is None
    assert payload["error"]["code"] == "system_python_not_found"
    assert "Python 3.11+" in payload["error"]["message"]
    assert "uv" in payload["error"]["action"]
    assert "pipx" in payload["error"]["action"]


def test_installer_dry_run_surfaces_one_voluntary_setup_action():
    result = subprocess.run(
        ["/bin/sh", "install.sh", "--dry-run"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "uv tool install --force" in result.stdout
    assert result.stdout.count("nomnom setup") == 1
    assert "one free USDA setup remains" in result.stdout
    assert "nomnom doctor --json" in result.stdout
    assert "before the first food log" in result.stdout


def test_agent_skill_contains_the_mandatory_issue_21_protocol():
    skill = (ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
    required_sentence = (
        "Base product/barcode capture works; to enable no-label generic-food lookup, "
        "one free USDA setup remains."
    )

    assert "Mandatory install protocol" in skill
    assert "--status-json" in skill
    assert "sanitized user/system-only PATH" in skill
    assert "nomnom --version" in skill
    assert "nomnom doctor --json" in skill
    assert "nomnom setup --status --json" in skill
    assert required_sentence in skill
    assert "exactly one voluntary action" in skill
    assert "must never type, receive, echo, or persist" in skill
    assert "Before every first meal" in skill
    assert "local-cache" in skill
    assert "Never run `pip install -e`" in skill
