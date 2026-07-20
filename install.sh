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

run_install() {
    if [ "$JSON_OUTPUT" -eq 1 ]; then
        "$@" >&2
    else
        "$@"
    fi
}

if [ "$DRY_RUN" -eq 1 ]; then
    say "[dry-run] prefer: uv tool install --force $REPO_URL"
    say "[dry-run] fallback: pipx install --force $REPO_URL"
    say "[dry-run] fallback: system Python 3.11+ -m pip install --user --upgrade $REPO_URL"
    say "[dry-run] discover the user tool executable directory and normal login-shell PATH"
    say "[dry-run] verify nomnom --version with a sanitized user/system PATH"
    say "[dry-run] verify and parse nomnom doctor --json before the first food log"
    say "Base product/barcode capture works; to enable no-label generic-food lookup, one free USDA setup remains."
    say "Voluntary one-time action: run 'nomnom setup' in your own terminal."
    if [ "$JSON_OUTPUT" -eq 1 ]; then
        STATUS="dry_run"
        emit_status
    fi
    exit 0
fi

INSTALL_METHOD=""
INSTALL_BIN_DIR=""
INSTALL_FAILURES=""

if command -v uv >/dev/null 2>&1; then
    if run_install uv tool install --force "$REPO_URL"; then
        INSTALL_METHOD="uv"
        INSTALL_BIN_DIR=$(uv tool dir --bin 2>/dev/null || true)
        [ -n "$INSTALL_BIN_DIR" ] || INSTALL_BIN_DIR=${UV_TOOL_BIN_DIR:-"$HOME/.local/bin"}
    else
        INSTALL_FAILURES="uv"
        note "uv tool install failed; trying the next user-level installer."
    fi
fi

if [ -z "$INSTALL_METHOD" ] && command -v pipx >/dev/null 2>&1; then
    if run_install pipx install --force "$REPO_URL"; then
        INSTALL_METHOD="pipx"
        INSTALL_BIN_DIR=$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || true)
        [ -n "$INSTALL_BIN_DIR" ] || INSTALL_BIN_DIR=${PIPX_BIN_DIR:-"$HOME/.local/bin"}
    else
        INSTALL_FAILURES="${INSTALL_FAILURES:+$INSTALL_FAILURES,}pipx"
        note "pipx install failed; trying the system-Python user-site fallback."
    fi
fi

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

python_search_path() {
    _python_result=""
    _python_old_ifs=$IFS
    IFS=:
    for _python_dir in ${PATH:-}; do
        [ -n "$_python_dir" ] || continue
        if [ -n "${VIRTUAL_ENV:-}" ]; then
            case "$_python_dir" in
                "$VIRTUAL_ENV"|"$VIRTUAL_ENV"/*) continue ;;
            esac
        fi
        case "$_python_dir" in
            *"/.venv"|*"/.venv/"*|*"/venv/"*|*"/.hermes/"*|*"/.codex/"*) continue ;;
        esac
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
            if ! /usr/bin/env -u VIRTUAL_ENV -u PYTHONPATH -u PYTHONHOME \
                "$_find_candidate" -c '
import pip  # noqa: F401
import sys
base_prefix = getattr(sys, "base_prefix", sys.prefix)
raise SystemExit(0 if sys.version_info >= (3, 11) and sys.prefix == base_prefix else 1)
' >/dev/null 2>&1; then
                continue
            fi
            _find_resolved=$(/usr/bin/env -u VIRTUAL_ENV -u PYTHONPATH -u PYTHONHOME \
                "$_find_candidate" -c '
import os, sys
print(os.path.realpath(sys.executable))
' 2>/dev/null || true)
            [ -n "$_find_resolved" ] || _find_resolved=$_find_candidate
            if [ -n "${VIRTUAL_ENV:-}" ]; then
                case "$_find_resolved" in
                    "$VIRTUAL_ENV"|"$VIRTUAL_ENV"/*) continue ;;
                esac
            fi
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
    if ! run_install /usr/bin/env \
        -u VIRTUAL_ENV -u PYTHONPATH -u PYTHONHOME -u PIP_REQUIRE_VIRTUALENV \
        "$SYSTEM_PYTHON" -m pip install --user --upgrade "$REPO_URL"; then
        fail \
            "installation_failed" \
            "The system-Python user-site installation failed${INSTALL_FAILURES:+ after $INSTALL_FAILURES failed}." \
            "Review the installer output, ensure Git and network access are available, then rerun."
    fi
    INSTALL_METHOD="user-site"
    INSTALL_BIN_DIR=$(/usr/bin/env -u VIRTUAL_ENV -u PYTHONPATH -u PYTHONHOME \
        "$SYSTEM_PYTHON" -c '
import sysconfig
print(sysconfig.get_path("scripts", scheme=sysconfig.get_preferred_scheme("user")))
' 2>/dev/null || true)
    [ -n "$INSTALL_BIN_DIR" ] || INSTALL_BIN_DIR="$HOME/.local/bin"
fi

CANDIDATE_DIRS=""
for _candidate_dir in \
    "$INSTALL_BIN_DIR" \
    "${UV_TOOL_BIN_DIR:-}" \
    "${PIPX_BIN_DIR:-}" \
    "${XDG_BIN_HOME:-}" \
    "$HOME/.local/bin" \
    "$HOME/bin"; do
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

normal_login_path() {
    _login_base="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/opt/local/bin"
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
    if [ -n "$_login_path" ]; then
        printf '%s' "$_login_path"
    else
        printf '%s' "$_login_base"
    fi
}

sanitize_normal_path() {
    _sanitize_source=$1
    _sanitize_result=""
    _sanitize_old_ifs=$IFS
    IFS=:
    for _sanitize_dir in $_sanitize_source; do
        [ -n "$_sanitize_dir" ] || continue
        if [ -n "${VIRTUAL_ENV:-}" ]; then
            case "$_sanitize_dir" in
                "$VIRTUAL_ENV"|"$VIRTUAL_ENV"/*) continue ;;
            esac
        fi
        case "$_sanitize_dir" in
            *"/.venv"|*"/.venv/"*|*"/venv/"*|*"/.hermes/"*|*"/.codex/"*) continue ;;
        esac
        case "$_sanitize_dir" in
            "$INSTALL_BIN_DIR"|"${UV_TOOL_BIN_DIR:-__unset__}"|"${PIPX_BIN_DIR:-__unset__}"|\
            "$HOME/.local/bin"|"$HOME/bin"|"${XDG_BIN_HOME:-__unset__}"|\
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

LOGIN_PATH=$(normal_login_path)
SANITIZED_LOGIN_PATH=$(sanitize_normal_path "$LOGIN_PATH")
VERIFY_PATH=$(append_path "$INSTALL_BIN_DIR" "$SANITIZED_LOGIN_PATH")

VERIFIED_EXECUTABLE=$(PATH="$VERIFY_PATH" command -v nomnom 2>/dev/null || true)
if [ -z "$VERIFIED_EXECUTABLE" ]; then
    fail \
        "verification_failed" \
        "nomnom is not executable under the sanitized user/system verification PATH." \
        "Ensure $INSTALL_BIN_DIR is executable and rerun the installer."
fi

if ! VERSION=$(/usr/bin/env -u VIRTUAL_ENV -u PYTHONPATH -u PYTHONHOME \
    PATH="$VERIFY_PATH" nomnom --version 2>&1); then
    fail \
        "version_verification_failed" \
        "The installed nomnom executable failed --version verification." \
        "Run $EXECUTABLE --version and review the reported error."
fi

if ! DOCTOR_OUTPUT=$(/usr/bin/env -u VIRTUAL_ENV -u PYTHONPATH -u PYTHONHOME \
    PATH="$VERIFY_PATH" nomnom doctor --json 2>&1); then
    fail \
        "doctor_verification_failed" \
        "The installed nomnom executable failed doctor JSON verification." \
        "Run $EXECUTABLE doctor --json and review the structured error."
fi

doctor_usda_bool() {
    printf '%s\n' "$DOCTOR_OUTPUT" | awk -v key="$1" '
        {
            if (!in_usda) {
                marker = index($0, "\"usda\"")
                if (!marker) next
                in_usda = 1
                text = substr($0, marker)
            } else {
                text = $0
            }
            true_pattern = "\"" key "\"[[:space:]]*:[[:space:]]*true"
            false_pattern = "\"" key "\"[[:space:]]*:[[:space:]]*false"
            if (text ~ true_pattern) { print "true"; exit }
            if (text ~ false_pattern) { print "false"; exit }
        }
    '
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
if [ "$LOGIN_EXECUTABLE" != "$EXECUTABLE" ]; then
    STATUS="installed_path_repair_needed"
    PATH_REPAIR="export PATH=\"$INSTALL_BIN_DIR:\$PATH\""
elif [ "$USDA_CONFIGURED" = "true" ] && [ "$USDA_REACHABLE" = "true" ]; then
    STATUS="installed_and_ready"
else
    STATUS="installed_needs_provider_setup"
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
    if [ -n "$PATH_REPAIR" ]; then
        say "One-time PATH repair: $PATH_REPAIR"
    fi
    if [ "$USDA_CONFIGURED" != "true" ] || [ "$USDA_REACHABLE" != "true" ]; then
        say "Base product/barcode capture works; to enable no-label generic-food lookup, one free USDA setup remains."
        if [ -t 1 ]; then
            say "That connection is voluntary; do it when you are ready."
        fi
        say "One action: run 'nomnom setup' in your own terminal."
    fi
fi

emit_status
exit 0
