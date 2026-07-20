from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "git+https://github.com/maxjustships/nomnomcli"


def test_tests_import_checkout_under_review():
    import nomnomcli

    assert Path(nomnomcli.__file__).resolve().is_relative_to(ROOT)


def test_installer_does_not_seed_target_login_path_with_global_tool_directories():
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert '_login_base=$(sanitize_target_login_path "${PATH:-}")' in installer
    assert '_login_base="/usr/local/bin:' not in installer


def _executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _nomnom_fixture(
    tmp_path: Path, *, usda_ready: bool = False, doctor_payload: str | None = None
) -> Path:
    if doctor_payload is None:
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
        f"""#!/usr/bin/python3
import os
import sys
from pathlib import Path

with open(Path(os.environ["HOME"]).parent / "trace.log", "a", encoding="utf-8") as trace:
    print(f"nomnom {{' '.join(sys.argv[1:])}}", file=trace)
if any(os.environ.get(name) for name in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")):
    print("private Python environment leaked into verification", file=sys.stderr)
    raise SystemExit(90)
if sys.argv[1:] == ["--version"]:
    print("nomnom 0.4.0")
elif sys.argv[1:] == ["doctor", "--json"]:
    print({doctor_payload!r})
else:
    raise SystemExit(2)
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
        (False, "installed_base_ready"),
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
    Path(environment["HOME"], ".profile").write_text(
        'PATH="$HOME/.local/bin:$PATH"\nexport PATH\n', encoding="utf-8"
    )
    _executable(
        tool_bin / "uv",
        f"""#!/bin/sh
printf 'uv %s\\n' "$*" >> {shlex.quote(str(Path(environment["TRACE"])))}
if [ "$1 $2 $3" = "tool install --force" ]; then
  mkdir -p "$UV_TOOL_BIN_DIR"
  cp {shlex.quote(str(fixture))} "$UV_TOOL_BIN_DIR/nomnom"
  exit 0
fi
if [ "$1 $2 $3" = "tool dir --bin" ]; then
  printf '%s\n' "$UV_TOOL_BIN_DIR"
  exit 0
fi
exit 2
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
        "generic_coverage": "enhanced" if usda_ready else "base",
        "optional_usda_setup": (
            None
            if usda_ready
            else {
                "command": "nomnom setup",
                "purpose": "broader no-photo raw/generic food coverage",
            }
        ),
    }
    trace = Path(environment["TRACE"]).read_text(encoding="utf-8")
    assert f"uv tool install --force {REPO_URL}" in trace
    assert "pipx " not in trace
    assert "nomnom --version" in trace
    assert "nomnom doctor --json" in trace
    assert before == after


def test_installer_isolates_all_tool_locations_from_poisoned_agent_environment(tmp_path):
    """Tool installation and discovery must use only the target user's defaults."""
    harness_bin = tmp_path / "harness-bin"
    home = tmp_path / "home"
    target_bin = home / ".local" / "bin"
    trace = tmp_path / "tool-environment.log"
    fixture = _nomnom_fixture(tmp_path, usda_ready=False)
    environment = _base_environment(tmp_path, harness_bin, fixture)
    poison_root = tmp_path / "agent-tool-state"
    poisoned = {
        "UV_TOOL_DIR": poison_root / "uv-tools",
        "UV_TOOL_BIN_DIR": poison_root / "uv-bin",
        "PIPX_HOME": poison_root / "pipx-home",
        "PIPX_BIN_DIR": poison_root / "pipx-bin",
        "XDG_BIN_HOME": poison_root / "xdg-bin",
        "XDG_DATA_HOME": poison_root / "xdg-data",
        "XDG_CACHE_HOME": poison_root / "xdg-cache",
        "XDG_STATE_HOME": poison_root / "xdg-state",
    }
    environment.update({name: str(path) for name, path in poisoned.items()})
    environment.update(
        {
            "XDG_CONFIG_HOME": str(poison_root / "xdg-config"),
            "NOMNOM_DB_PATH": str(poison_root / "existing.sqlite3"),
            "VIRTUAL_ENV": str(poison_root / "venv"),
        }
    )
    target_bin.mkdir(parents=True)
    Path(environment["HOME"], ".profile").write_text(
        'PATH="$HOME/.local/bin:$PATH"\nexport PATH\n', encoding="utf-8"
    )
    _executable(
        target_bin / "uv",
        f"""#!/bin/sh
{{
  printf 'uv %s\\n' "$*"
  for name in \
    UV_TOOL_DIR UV_TOOL_BIN_DIR PIPX_HOME PIPX_BIN_DIR XDG_BIN_HOME XDG_DATA_HOME \
    XDG_CACHE_HOME XDG_STATE_HOME XDG_CONFIG_HOME VIRTUAL_ENV NOMNOM_DB_PATH
  do
    value=$(printenv "$name" || printf '__UNSET__')
    printf '%s=%s\\n' "$name" "$value"
  done
}} >> {shlex.quote(str(trace))}
if [ "$1 $2 $3" = "tool install --force" ]; then
  mkdir -p "$UV_TOOL_BIN_DIR"
  cp {shlex.quote(str(fixture))} "$UV_TOOL_BIN_DIR/nomnom"
  exit 0
fi
if [ "$1 $2 $3" = "tool dir --bin" ]; then
  printf '%s\\n' "$UV_TOOL_BIN_DIR"
  exit 0
fi
exit 2
""",
    )

    result = _run_installer(environment, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "installed_base_ready"
    assert payload["executable"] == str(target_bin / "nomnom")
    assert (target_bin / "nomnom").is_file()
    assert not poison_root.exists()

    tool_trace = trace.read_text(encoding="utf-8")
    assert tool_trace.count(f"uv tool install --force {REPO_URL}") == 1
    assert tool_trace.count("uv tool dir --bin") == 1
    expected = {
        "UV_TOOL_DIR": str(home / ".local" / "share" / "uv" / "tools"),
        "UV_TOOL_BIN_DIR": str(target_bin),
        "PIPX_HOME": str(home / ".local" / "share" / "pipx"),
        "PIPX_BIN_DIR": str(target_bin),
        "XDG_BIN_HOME": "__UNSET__",
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "VIRTUAL_ENV": "__UNSET__",
        "NOMNOM_DB_PATH": "__UNSET__",
    }
    for name, value in expected.items():
        assert tool_trace.count(f"{name}={value}") == 2
    assert str(poison_root) not in tool_trace

    normal_shell = subprocess.run(
        ["/bin/sh", "-lc", "command -v nomnom && nomnom --version"],
        env={
            "HOME": str(home),
            "SHELL": "/bin/sh",
            "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert normal_shell.returncode == 0, normal_shell.stderr
    assert normal_shell.stdout.splitlines() == [str(target_bin / "nomnom"), "nomnom 0.4.0"]


@pytest.mark.parametrize(
    "doctor_payload",
    [
        pytest.param(
            (
                "{\n"
                '  "providers": {\n'
                '    "openfoodfacts": {"configured": true, "full_text_search_ready": false, '
                '"product_lookup_reachable": true},\n'
                '    "usda": {"configured": false, "key_source": null, "reachable": false}\n'
                "  }\n"
                "}"
            ),
            id="multiline-doctor-output-from-smoke",
        ),
        pytest.param(
            (
                "{\n"
                '  "providers": {\n'
                '    "openfoodfacts": {"configured": true, "full_text_search_ready": true, '
                '"product_lookup_reachable": true},\n'
                '    "usda": {\n'
                '      "diagnostic": {"configured": true, "reachable": true},\n'
                '      "reachable": false,\n'
                '      "key_source": null,\n'
                '      "configured": false\n'
                "    }\n"
                "  }\n"
                "}"
            ),
            id="usda-fields-reordered-with-nested-true-values",
        ),
    ],
)
def test_installer_reads_only_top_level_usda_provider_booleans(tmp_path, doctor_payload):
    harness_bin = tmp_path / "harness-bin"
    tool_bin = tmp_path / "home" / ".local" / "bin"
    fixture = _nomnom_fixture(tmp_path, doctor_payload=doctor_payload)
    environment = _base_environment(tmp_path, harness_bin, fixture)
    Path(environment["HOME"], ".profile").write_text(
        'PATH="$HOME/.local/bin:$PATH"\nexport PATH\n', encoding="utf-8"
    )
    _executable(
        tool_bin / "uv",
        f"""#!/bin/sh
if [ "$1 $2 $3" = "tool install --force" ]; then
  mkdir -p "$UV_TOOL_BIN_DIR"
  cp {shlex.quote(str(fixture))} "$UV_TOOL_BIN_DIR/nomnom"
  exit 0
fi
if [ "$1 $2 $3" = "tool dir --bin" ]; then
  printf '%s\n' "$UV_TOOL_BIN_DIR"
  exit 0
fi
exit 2
""",
    )

    result = _run_installer(environment, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "installed_base_ready"
    assert payload["generic_coverage"] == "base"
    assert payload["optional_usda_setup"]["command"] == "nomnom setup"
    assert payload["path_repair"] is None


def test_installer_uses_pipx_when_uv_is_unavailable(tmp_path):
    harness_bin = tmp_path / "harness-bin"
    tool_bin = tmp_path / "home" / ".local" / "bin"
    fixture = _nomnom_fixture(tmp_path, usda_ready=False)
    environment = _base_environment(tmp_path, harness_bin, fixture)
    poison_root = tmp_path / "agent-tool-state"
    environment.update(
        {
            "UV_TOOL_DIR": str(poison_root / "uv-tools"),
            "UV_TOOL_BIN_DIR": str(poison_root / "uv-bin"),
            "PIPX_HOME": str(poison_root / "pipx-home"),
            "PIPX_BIN_DIR": str(poison_root / "pipx-bin"),
            "XDG_BIN_HOME": str(poison_root / "xdg-bin"),
            "XDG_DATA_HOME": str(poison_root / "xdg-data"),
            "XDG_CACHE_HOME": str(poison_root / "xdg-cache"),
            "XDG_STATE_HOME": str(poison_root / "xdg-state"),
        }
    )
    trace_path = shlex.quote(str(Path(environment["TRACE"])))
    _executable(
        tool_bin / "pipx",
        f"""#!/bin/sh
printf 'pipx %s\\n' "$*" >> {trace_path}
for name in \
  UV_TOOL_DIR UV_TOOL_BIN_DIR PIPX_HOME PIPX_BIN_DIR XDG_BIN_HOME XDG_DATA_HOME \
  XDG_CACHE_HOME XDG_STATE_HOME
do
  value=$(printenv "$name" || printf '__UNSET__')
  printf '%s=%s\\n' "$name" "$value" >> {trace_path}
done
if [ "$1 $2 $3" = "install --force git+https://github.com/maxjustships/nomnomcli" ]; then
  mkdir -p "$PIPX_BIN_DIR"
  cp {shlex.quote(str(fixture))} "$PIPX_BIN_DIR/nomnom"
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
    assert payload["generic_coverage"] == "base"
    assert payload["optional_usda_setup"] == {
        "command": "nomnom setup",
        "purpose": "broader no-photo raw/generic food coverage",
    }
    assert f"pipx install --force {REPO_URL}" in Path(environment["TRACE"]).read_text()
    pipx_trace = Path(environment["TRACE"]).read_text(encoding="utf-8")
    assert str(poison_root) not in pipx_trace
    assert pipx_trace.count(f"PIPX_HOME={tool_bin.parent / 'share' / 'pipx'}") == 2
    assert pipx_trace.count(f"PIPX_BIN_DIR={tool_bin}") == 2
    assert pipx_trace.count("XDG_BIN_HOME=__UNSET__") == 2
    assert not poison_root.exists()

    human_result = _run_installer(environment)

    assert human_result.returncode == 0, human_result.stderr
    assert "Status: installed_path_repair_needed" in human_result.stdout
    assert "One-time PATH repair:" in human_result.stdout
    assert "Generic/raw coverage: base" in human_result.stdout
    assert "Optional USDA enhancement: run 'nomnom setup'" in human_result.stdout


def test_installer_user_site_fallback_ignores_outside_path_installers_and_agent_venv_python(
    tmp_path,
):
    agent_bin = tmp_path / "agent-venv" / "bin"
    tool_bin = tmp_path / "home" / ".local" / "bin"
    fixture = _nomnom_fixture(tmp_path, usda_ready=True)
    environment = _base_environment(tmp_path, agent_bin, fixture)
    environment["PATH"] = f"{agent_bin}:/usr/bin:/bin"
    environment["VIRTUAL_ENV"] = str(agent_bin.parent)
    _executable(
        agent_bin / "python3",
        """#!/bin/sh
printf 'agent-python %s\n' "$*" >> "$TRACE"
exit 0
""",
    )
    _executable(
        tool_bin / "python3.11",
        f"""#!/bin/sh
printf 'system-python %s\\n' "$*" >> {shlex.quote(str(Path(environment["TRACE"])))}
if [ "$1" = "-c" ]; then
  case "$2" in
    *sysconfig*) printf '%s\n' "$HOME/.local/bin" ;;
    *sys.executable*) printf '%s\n' "$0" ;;
  esac
  exit 0
fi
if [ "$1 $2" = "-m pip" ]; then
  mkdir -p "$HOME/.local/bin"
  cp {shlex.quote(str(fixture))} "$HOME/.local/bin/nomnom"
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
    assert "uv " not in trace
    assert "pipx " not in trace
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


def test_installer_verification_ignores_agent_xdg_and_nomnom_environment(tmp_path):
    harness_bin = tmp_path / "harness-bin"
    tool_bin = tmp_path / "home" / ".local" / "bin"
    fixture = _executable(
        tmp_path / "nomnom-fixture",
        """#!/usr/bin/python3
import json
import os
import sys
from pathlib import Path

tracked = (
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "NOMNOM_USDA_KEY",
    "NOMNOM_GENERIC_PROXY_POLICY",
    "NOMNOM_DB_PATH",
    "NOMNOM_DISABLE_OFF",
    "NOMNOM_OFFLINE",
)
with open(Path(os.environ["HOME"]).parent / "trace.log", "a", encoding="utf-8") as trace:
    print(json.dumps({name: os.environ.get(name) for name in tracked}, sort_keys=True), file=trace)

if sys.argv[1:] == ["--version"]:
    print("nomnom 0.4.0")
elif sys.argv[1:] == ["doctor", "--json"]:
    config_home = Path(os.environ["XDG_CONFIG_HOME"])
    configured = bool(os.environ.get("NOMNOM_USDA_KEY")) or (
        config_home / "nomnomcli" / "config.toml"
    ).exists()
    print(json.dumps({"providers": {"usda": {"configured": configured, "reachable": configured}}}))
else:
    raise SystemExit(2)
""",
    )
    environment = _base_environment(tmp_path, harness_bin, fixture)
    environment.update(
        {
            "XDG_CONFIG_HOME": str(tmp_path / "agent-config"),
            "XDG_CACHE_HOME": str(tmp_path / "agent-cache"),
            "XDG_DATA_HOME": str(tmp_path / "agent-data"),
            "XDG_STATE_HOME": str(tmp_path / "agent-state"),
            "NOMNOM_USDA_KEY": "agent-usda-key",
            "NOMNOM_GENERIC_PROXY_POLICY": "exact_only",
            "NOMNOM_DISABLE_OFF": "1",
            "NOMNOM_OFFLINE": "1",
        }
    )
    agent_config = Path(environment["XDG_CONFIG_HOME"]) / "nomnomcli"
    agent_config.mkdir(parents=True)
    (agent_config / "config.toml").write_text(
        "[providers.usda]\napi_key = 'agent-config-key'\n", encoding="utf-8"
    )
    Path(environment["HOME"], ".profile").write_text(
        'PATH="$HOME/.local/bin:$PATH"\nexport PATH\n', encoding="utf-8"
    )
    _executable(
        tool_bin / "uv",
        f"""#!/bin/sh
if [ "$1 $2 $3" = "tool install --force" ]; then
  mkdir -p "$UV_TOOL_BIN_DIR"
  cp {shlex.quote(str(fixture))} "$UV_TOOL_BIN_DIR/nomnom"
  exit 0
fi
if [ "$1 $2 $3" = "tool dir --bin" ]; then
  printf '%s\n' "$UV_TOOL_BIN_DIR"
  exit 0
fi
exit 2
""",
    )

    result = _run_installer(environment, "--status-json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "installed_base_ready"
    assert payload["generic_coverage"] == "base"
    invocation_environments = [
        json.loads(line)
        for line in Path(environment["TRACE"]).read_text().splitlines()
        if line.startswith("{")
    ]
    assert len(invocation_environments) == 2
    for invocation_environment in invocation_environments:
        assert invocation_environment == {
            "NOMNOM_DB_PATH": None,
            "NOMNOM_DISABLE_OFF": None,
            "NOMNOM_GENERIC_PROXY_POLICY": None,
            "NOMNOM_OFFLINE": None,
            "NOMNOM_USDA_KEY": None,
            "XDG_CACHE_HOME": None,
            "XDG_CONFIG_HOME": str(Path(environment["HOME"]) / ".config"),
            "XDG_DATA_HOME": None,
            "XDG_STATE_HOME": None,
        }


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
    assert "Optional USDA enhancement" in result.stdout
    assert "nomnom doctor --json" in result.stdout
    assert "before the first food log" in result.stdout


def test_agent_skill_treats_no_token_install_as_successful_base_mode():
    skill = (ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")

    assert "Mandatory install protocol" in skill
    assert "--status-json" in skill
    assert "sanitized user/system-only environment" in skill
    assert "XDG_CONFIG_HOME=$HOME/.config" in skill
    assert "clear every `NOMNOM_*` override" in skill
    assert "nomnom --version" in skill
    assert "nomnom doctor --json" in skill
    assert "installed_base_ready" in skill
    assert "Base tracking is ready without a USDA key." in skill
    assert "Do not ask for setup after a successful base install." in skill
    assert "broader no-photo generic/raw-food coverage" in skill
    assert "food_needs_source" in skill
    assert "must never type, receive, echo, or persist" in skill
    assert "local-cache" in skill
    assert "Never run `pip install -e`" in skill


def test_readme_documents_base_ready_install_and_optional_usda_contract():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "installed_base_ready" in readme
    assert "generic_coverage" in readme
    assert "status: base_ready" in readme
    assert "food_needs_source" in readme
    assert "optional broader no-photo generic/raw-food coverage" in readme
    assert "installed_needs_provider_setup" not in readme
    assert "returns `usda_key_required`" not in readme
