#!/bin/sh
set -u

REPO_URL="git+https://github.com/maxjustships/nomnomcli"
SKILL_URL="https://raw.githubusercontent.com/maxjustships/nomnomcli/main/skill/SKILL.md"
DRY_RUN=0
JSON_OUTPUT=0
STATUS=""
EXECUTABLE=""
VERSION=""
ERROR_CODE=""
ERROR_MESSAGE=""
ERROR_ACTION=""
PATH_REPAIR=""
GENERIC_COVERAGE=""
OPTIONAL_USDA_SETUP=0

usage() {
    printf '%s\n' "Usage: sh install.sh [--dry-run] [--json|--status-json]"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --json|--status-json) JSON_OUTPUT=1 ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
    shift
done

say() {
    [ "$JSON_OUTPUT" -eq 0 ] && printf '%s\n' "$*"
}

note() {
    if [ "$JSON_OUTPUT" -eq 1 ]; then
        printf '%s\n' "$*" >&2
    else
        printf '%s\n' "$*"
    fi
}

json_quote() {
    printf '%s' "$1" | awk '
        BEGIN { printf "\"" }
        {
            if (NR > 1) printf "\\n"
            gsub(/\\/, "\\\\")
            gsub(/"/, "\\\"")
            gsub(/\r/, "\\r")
            gsub(/\t/, "\\t")
            printf "%s", $0
        }
        END { printf "\"" }
    '
}

json_value_or_null() {
    if [ -n "$1" ]; then
        json_quote "$1"
    else
        printf 'null'
    fi
}

emit_status() {
    if [ "$JSON_OUTPUT" -eq 1 ]; then
        printf '{"status":'
        json_quote "$STATUS"
        printf ',"executable":'
        json_value_or_null "$EXECUTABLE"
        printf ',"version":'
        json_value_or_null "$VERSION"
        printf ',"error":'
        if [ -n "$ERROR_CODE" ]; then
            printf '{"code":'
            json_quote "$ERROR_CODE"
            printf ',"message":'
            json_quote "$ERROR_MESSAGE"
            printf ',"action":'
            json_quote "$ERROR_ACTION"
            printf '}'
        else
            printf 'null'
        fi
        printf ',"path_repair":'
        json_value_or_null "$PATH_REPAIR"
        printf ',"generic_coverage":'
        json_value_or_null "$GENERIC_COVERAGE"
        printf ',"optional_usda_setup":'
        if [ "$OPTIONAL_USDA_SETUP" -eq 1 ]; then
            printf '{"command":"nomnom setup","purpose":'
            json_quote "broader no-photo raw/generic food coverage"
            printf '}'
        else
            printf 'null'
        fi
        printf '}\n'
    fi
}

fail() {
    STATUS="error"
    ERROR_CODE=$1
    ERROR_MESSAGE=$2
    ERROR_ACTION=$3
    if [ "$JSON_OUTPUT" -eq 0 ]; then
        printf 'Error: %s\nAction: %s\n' "$ERROR_MESSAGE" "$ERROR_ACTION" >&2
    fi
    emit_status
    exit 1
}

target_login_path() {
    # The invoking PATH is the only reliable statement of which system paths
    # belong to this target user.  Never add a global tool directory here: an
    # agent or CI image may have installed uv/pipx there for itself.
    _login_base=$(sanitize_target_login_path "${PATH:-}")
    _login_shell=${SHELL:-/bin/sh}
    if [ ! -x "$_login_shell" ]; then
        printf '%s' "$_login_base"
        return
    fi
    _login_environment=$(/usr/bin/env -i \
        HOME="$HOME" \
        USER="${USER:-}" \
        LOGNAME="${LOGNAME:-${USER:-}}" \
        SHELL="$_login_shell" \
        PATH="$_login_base" \
        "$_login_shell" -lc '/usr/bin/env' 2>/dev/null || true)
    _login_path=$(printf '%s\n' "$_login_environment" | awk '
        /^PATH=/ { sub(/^PATH=/, ""); path = $0 }
        END { printf "%s", path }
    ')
    _login_path=$(restrict_target_login_path "$_login_path" "$_login_base")
    if [ -n "$_login_path" ]; then
        printf '%s' "$_login_path"
    else
        printf '%s' "$_login_base"
    fi
}

append_path() {
    _append_current=$1
    _append_dir=$2
    if [ -z "$_append_dir" ]; then
        printf '%s' "$_append_current"
    elif [ -z "$_append_current" ]; then
        printf '%s' "$_append_dir"
    else
        case ":$_append_current:" in
            *":$_append_dir:"*) printf '%s' "$_append_current" ;;
            *) printf '%s:%s' "$_append_current" "$_append_dir" ;;
        esac
    fi
}

sanitize_target_login_path() {
    _sanitize_source=$1
    _sanitize_result=""
    _sanitize_old_ifs=$IFS
    IFS=:
    for _sanitize_dir in $_sanitize_source; do
        [ -n "$_sanitize_dir" ] || continue
        case "$_sanitize_dir" in
            "$HOME/.local/bin"|"$HOME/bin"|\
            /bin|/bin/*|/sbin|/sbin/*|/usr/bin|/usr/bin/*|/usr/sbin|/usr/sbin/*|\
            /usr/local/bin|/usr/local/bin/*|/opt/homebrew/bin|/opt/homebrew/bin/*|\
            /opt/local/bin|/opt/local/bin/*)
                _sanitize_result=$(append_path "$_sanitize_result" "$_sanitize_dir")
                ;;
        esac
    done
    IFS=$_sanitize_old_ifs
    printf '%s' "$_sanitize_result"
}

restrict_target_login_path() {
    _restrict_login_path=$(sanitize_target_login_path "$1")
    _restrict_base_path=$2
    _restrict_result=""
    _restrict_old_ifs=$IFS
    IFS=:
    for _restrict_dir in $_restrict_login_path; do
        [ -n "$_restrict_dir" ] || continue
        case ":$_restrict_base_path:" in
            *":$_restrict_dir:"*)
                _restrict_result=$(append_path "$_restrict_result" "$_restrict_dir")
                continue
                ;;
        esac
        # A target login shell may add these conventional per-user tool
        # locations.  Do not accept system-wide additions injected by /etc/profile.
        case "$_restrict_dir" in
            "$HOME/.local/bin"|"$HOME/bin")
                _restrict_result=$(append_path "$_restrict_result" "$_restrict_dir")
                ;;
        esac
    done
    IFS=$_restrict_old_ifs
    printf '%s' "$_restrict_result"
}

# All installer tool selection, invocation, and discovery use this target-user
# environment. Do not read UV/PIPX/XDG locations from the invoking agent.
TARGET_BIN_DIR="$HOME/.local/bin"
TARGET_UV_TOOL_DIR="$HOME/.local/share/uv/tools"
TARGET_PIPX_HOME="$HOME/.local/share/pipx"
TARGET_LOGIN_PATH=$(target_login_path)
TARGET_COMMAND_PATH=$(append_path "$TARGET_BIN_DIR" "$(sanitize_target_login_path "$TARGET_LOGIN_PATH")")
[ -n "$TARGET_COMMAND_PATH" ] || TARGET_COMMAND_PATH="$TARGET_BIN_DIR:/usr/bin:/bin"

run_target_environment() {
    /usr/bin/env -i \
        HOME="$HOME" \
        USER="${USER:-}" \
        LOGNAME="${LOGNAME:-${USER:-}}" \
        SHELL="${SHELL:-/bin/sh}" \
        PATH="$TARGET_COMMAND_PATH" \
        XDG_CONFIG_HOME="$HOME/.config" \
        XDG_DATA_HOME="$HOME/.local/share" \
        XDG_CACHE_HOME="$HOME/.cache" \
        XDG_STATE_HOME="$HOME/.local/state" \
        PYTHONUSERBASE="$HOME/.local" \
        UV_TOOL_DIR="$TARGET_UV_TOOL_DIR" \
        UV_TOOL_BIN_DIR="$TARGET_BIN_DIR" \
        PIPX_HOME="$TARGET_PIPX_HOME" \
        PIPX_BIN_DIR="$TARGET_BIN_DIR" \
        "$@"
}

find_target_command() {
    PATH="$TARGET_COMMAND_PATH" command -v "$1" 2>/dev/null || true
}

run_install() {
    if [ "$JSON_OUTPUT" -eq 1 ]; then
        run_target_environment "$@" >&2
    else
        run_target_environment "$@"
    fi
}

if [ "$DRY_RUN" -eq 1 ]; then
    say "[dry-run] prefer: uv tool install --force $REPO_URL"
    say "[dry-run] fallback: pipx install --force $REPO_URL"
    say "[dry-run] fallback: system Python 3.11+ -m pip install --user --upgrade $REPO_URL"
    say "[dry-run] discover the user tool executable directory and normal login-shell PATH"
    say "[dry-run] verify nomnom --version with a sanitized user/system PATH"
    say "[dry-run] verify and parse nomnom doctor --json before the first food log"
    say "Base product/barcode/cache/label capture is ready without a key."
    say "Optional USDA enhancement: run 'nomnom setup' for broader no-photo raw/generic food coverage."
    if [ "$JSON_OUTPUT" -eq 1 ]; then
        STATUS="dry_run"
        GENERIC_COVERAGE="base"
        OPTIONAL_USDA_SETUP=1
        emit_status
    fi
    exit 0
fi

INSTALL_METHOD=""
INSTALL_BIN_DIR=""
INSTALL_FAILURES=""

UV_COMMAND=$(find_target_command uv)
if [ -n "$UV_COMMAND" ]; then
    if run_install "$UV_COMMAND" tool install --force "$REPO_URL"; then
        INSTALL_METHOD="uv"
        INSTALL_BIN_DIR=$(run_target_environment "$UV_COMMAND" tool dir --bin 2>/dev/null || true)
        if [ "$INSTALL_BIN_DIR" != "$TARGET_BIN_DIR" ]; then
            fail \
                "tool_location_mismatch" \
                "uv reported a tool executable directory outside the target user's default bin." \
                "Ensure uv can use $TARGET_BIN_DIR, then rerun the installer."
        fi
    else
        INSTALL_FAILURES="uv"
        note "uv tool install failed; trying the next user-level installer."
    fi
fi

PIPX_COMMAND=$(find_target_command pipx)
if [ -z "$INSTALL_METHOD" ] && [ -n "$PIPX_COMMAND" ]; then
    if run_install "$PIPX_COMMAND" install --force "$REPO_URL"; then
        INSTALL_METHOD="pipx"
        INSTALL_BIN_DIR=$(run_target_environment "$PIPX_COMMAND" environment --value PIPX_BIN_DIR 2>/dev/null || true)
        if [ "$INSTALL_BIN_DIR" != "$TARGET_BIN_DIR" ]; then
            fail \
                "tool_location_mismatch" \
                "pipx reported an executable directory outside the target user's default bin." \
                "Ensure pipx can use $TARGET_BIN_DIR, then rerun the installer."
        fi
    else
        INSTALL_FAILURES="${INSTALL_FAILURES:+$INSTALL_FAILURES,}pipx"
        note "pipx install failed; trying the system-Python user-site fallback."
    fi
fi

python_search_path() {
    _python_result=""
    _python_old_ifs=$IFS
    IFS=:
    for _python_dir in $TARGET_COMMAND_PATH; do
        [ -n "$_python_dir" ] || continue
        _python_result=$(append_path "$_python_result" "$_python_dir")
    done
    IFS=$_python_old_ifs
    printf '%s' "$_python_result"
}

find_system_python() {
    _find_path=$(python_search_path)
    _find_seen=""
    _find_old_ifs=$IFS
    IFS=:
    for _find_dir in $_find_path; do
        for _find_name in python3 python3.14 python3.13 python3.12 python3.11; do
            _find_candidate="$_find_dir/$_find_name"
            [ -x "$_find_candidate" ] || continue
            case ":$_find_seen:" in
                *":$_find_candidate:"*) continue ;;
            esac
            _find_seen="${_find_seen:+$_find_seen:}$_find_candidate"
            if ! run_target_environment "$_find_candidate" -c '
import pip  # noqa: F401
import sys
base_prefix = getattr(sys, "base_prefix", sys.prefix)
raise SystemExit(0 if sys.version_info >= (3, 11) and sys.prefix == base_prefix else 1)
' >/dev/null 2>&1; then
                continue
            fi
            _find_resolved=$(run_target_environment "$_find_candidate" -c '
import os, sys
print(os.path.realpath(sys.executable))
' 2>/dev/null || true)
            [ -n "$_find_resolved" ] || _find_resolved=$_find_candidate
            IFS=$_find_old_ifs
            printf '%s' "$_find_candidate"
            return 0
        done
    done
    IFS=$_find_old_ifs
    return 1
}

if [ -z "$INSTALL_METHOD" ]; then
    SYSTEM_PYTHON=$(find_system_python || true)
    if [ -z "$SYSTEM_PYTHON" ]; then
        fail \
            "system_python_not_found" \
            "No non-virtualenv system Python 3.11+ was found for the user-site fallback." \
            "Install uv or pipx, or install Python 3.11+ in your normal shell PATH, then rerun this installer."
    fi
    note "No isolated tool installer completed; using the system-Python user-site fallback."
    if ! run_install "$SYSTEM_PYTHON" -m pip install --user --upgrade "$REPO_URL"; then
        fail \
            "installation_failed" \
            "The system-Python user-site installation failed${INSTALL_FAILURES:+ after $INSTALL_FAILURES failed}." \
            "Review the installer output, ensure Git and network access are available, then rerun."
    fi
    INSTALL_METHOD="user-site"
    INSTALL_BIN_DIR=$(run_target_environment "$SYSTEM_PYTHON" -c '
import sysconfig
print(sysconfig.get_path("scripts", scheme=sysconfig.get_preferred_scheme("user")))
' 2>/dev/null || true)
    if [ "$INSTALL_BIN_DIR" != "$TARGET_BIN_DIR" ]; then
        fail \
            "tool_location_mismatch" \
            "The system-Python user-site fallback reported an executable directory outside the target user's default bin." \
            "Ensure Python can use $TARGET_BIN_DIR, then rerun the installer."
    fi
fi

CANDIDATE_DIRS=""
for _candidate_dir in \
    "$INSTALL_BIN_DIR" \
    "$TARGET_BIN_DIR"; do
    [ -n "$_candidate_dir" ] || continue
    CANDIDATE_DIRS=$(append_path "$CANDIDATE_DIRS" "$_candidate_dir")
done

_candidate_old_ifs=$IFS
IFS=:
for _candidate_dir in $CANDIDATE_DIRS; do
    if [ -x "$_candidate_dir/nomnom" ]; then
        EXECUTABLE="$_candidate_dir/nomnom"
        break
    fi
done
IFS=$_candidate_old_ifs

if [ -z "$EXECUTABLE" ]; then
    fail \
        "executable_not_found" \
        "$INSTALL_METHOD completed but no user-level nomnom executable was found." \
        "Inspect $INSTALL_BIN_DIR and rerun with --status-json for structured diagnostics."
fi

sanitize_normal_path() {
    sanitize_target_login_path "$1"
}

LOGIN_PATH=$TARGET_LOGIN_PATH
SANITIZED_LOGIN_PATH=$(sanitize_normal_path "$LOGIN_PATH")
VERIFY_PATH=$(append_path "$INSTALL_BIN_DIR" "$SANITIZED_LOGIN_PATH")

# Bootstrap verification observes only the target user's default configuration.
# Do not inherit an invoking agent's XDG roots or NOMNOM_* overrides/secrets.
run_verification() {
    /usr/bin/env -i \
        HOME="$HOME" \
        USER="${USER:-}" \
        LOGNAME="${LOGNAME:-${USER:-}}" \
        SHELL="${SHELL:-/bin/sh}" \
        PATH="$VERIFY_PATH" \
        XDG_CONFIG_HOME="$HOME/.config" \
        "$@"
}

VERIFIED_EXECUTABLE=$(PATH="$VERIFY_PATH" command -v nomnom 2>/dev/null || true)
if [ -z "$VERIFIED_EXECUTABLE" ]; then
    fail \
        "verification_failed" \
        "nomnom is not executable under the sanitized user/system verification PATH." \
        "Ensure $INSTALL_BIN_DIR is executable and rerun the installer."
fi

if ! VERSION=$(run_verification nomnom --version 2>&1); then
    fail \
        "version_verification_failed" \
        "The installed nomnom executable failed --version verification." \
        "Run $EXECUTABLE --version and review the reported error."
fi

if ! DOCTOR_OUTPUT=$(run_verification nomnom doctor --json 2>&1); then
    fail \
        "doctor_verification_failed" \
        "The installed nomnom executable failed doctor JSON verification." \
        "Run $EXECUTABLE doctor --json and review the structured error."
fi

doctor_usda_bool() {
    _doctor_key=$1
    _doctor_python=$(awk '
        NR == 1 && /^#!/ { print substr($0, 3); exit }
    ' "$EXECUTABLE")
    [ -n "$_doctor_python" ] && [ -x "$_doctor_python" ] || return 1
    printf '%s' "$DOCTOR_OUTPUT" | /usr/bin/env -u VIRTUAL_ENV -u PYTHONPATH -u PYTHONHOME \
        "$_doctor_python" -c '
import json
import sys

try:
    value = json.load(sys.stdin)["providers"]["usda"][sys.argv[1]]
except (json.JSONDecodeError, KeyError, TypeError):
    raise SystemExit(1)
if type(value) is not bool:
    raise SystemExit(1)
print(str(value).lower())
' "$_doctor_key"
}

USDA_CONFIGURED=$(doctor_usda_bool configured)
USDA_REACHABLE=$(doctor_usda_bool reachable)
if [ -z "$USDA_CONFIGURED" ] || [ -z "$USDA_REACHABLE" ]; then
    fail \
        "doctor_json_invalid" \
        "nomnom doctor --json did not contain the expected USDA configured/reachable status." \
        "Run $EXECUTABLE doctor --json and reinstall if its schema is incompatible."
fi

LOGIN_EXECUTABLE=$(PATH="$SANITIZED_LOGIN_PATH" command -v nomnom 2>/dev/null || true)
if [ "$USDA_CONFIGURED" = "true" ] && [ "$USDA_REACHABLE" = "true" ]; then
    GENERIC_COVERAGE="enhanced"
    OPTIONAL_USDA_SETUP=0
else
    GENERIC_COVERAGE="base"
    OPTIONAL_USDA_SETUP=1
fi
if [ "$LOGIN_EXECUTABLE" != "$EXECUTABLE" ]; then
    STATUS="installed_path_repair_needed"
    PATH_REPAIR="export PATH=\"$INSTALL_BIN_DIR:\$PATH\""
elif [ "$USDA_CONFIGURED" = "true" ] && [ "$USDA_REACHABLE" = "true" ]; then
    STATUS="installed_and_ready"
else
    STATUS="installed_base_ready"
fi

if [ -d "$HOME/.hermes" ]; then
    SKILL_DIR="$HOME/.hermes/skills/nomnomcli"
    if mkdir -p "$SKILL_DIR"; then
        if [ -f "skill/SKILL.md" ]; then
            cp "skill/SKILL.md" "$SKILL_DIR/SKILL.md"
        elif command -v curl >/dev/null 2>&1; then
            curl -fsSL "$SKILL_URL" -o "$SKILL_DIR/SKILL.md" || note "Warning: agent skill download failed."
        else
            note "Warning: curl is required to install the optional Hermes skill."
        fi
    else
        note "Warning: the optional Hermes skill directory could not be created."
    fi
fi

if [ "$JSON_OUTPUT" -eq 0 ]; then
    say "Installed: $EXECUTABLE"
    say "Version: $VERSION"
    say "Status: $STATUS"
    say "Generic/raw coverage: $GENERIC_COVERAGE"
    if [ -n "$PATH_REPAIR" ]; then
        say "One-time PATH repair: $PATH_REPAIR"
    fi
    if [ "$USDA_CONFIGURED" != "true" ] || [ "$USDA_REACHABLE" != "true" ]; then
        say "Base product/barcode/cache/label capture is ready without a key."
        if [ -t 1 ]; then
            say "That connection is voluntary; do it when you are ready."
        fi
        say "Optional USDA enhancement: run 'nomnom setup' for broader no-photo raw/generic food coverage."
    fi
fi

emit_status
exit 0
