#!/bin/sh
set -eu

REPO_URL="git+https://github.com/maxjustships/nomnomcli"
SKILL_URL="https://raw.githubusercontent.com/maxjustships/nomnomcli/main/skill/SKILL.md"
DRY_RUN=0

usage() {
    printf '%s\n' "Usage: sh install.sh [--dry-run]"
}

if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
    shift
fi
if [ "$#" -ne 0 ]; then
    usage >&2
    exit 2
fi

say() {
    printf '%s\n' "$*"
}

run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        say "[dry-run] $*"
    else
        "$@"
    fi
}

if [ "$DRY_RUN" -eq 0 ]; then
    if ! command -v python3 >/dev/null 2>&1; then
        say "Error: Python 3.11+ is required." >&2
        exit 1
    fi
    if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
        say "Error: Python 3.11+ is required." >&2
        exit 1
    fi
else
    say "[dry-run] check for Python 3.11+"
fi

if command -v pipx >/dev/null 2>&1; then
    run pipx install --force "$REPO_URL"
else
    say "pipx not found; using the user-site pip fallback."
    run python3 -m pip install --user --upgrade "$REPO_URL"
fi

if [ -d "${HOME}/.hermes" ]; then
    SKILL_DIR="${HOME}/.hermes/skills/nomnomcli"
    run mkdir -p "$SKILL_DIR"
    if [ -f "skill/SKILL.md" ]; then
        run cp "skill/SKILL.md" "$SKILL_DIR/SKILL.md"
    elif command -v curl >/dev/null 2>&1; then
        run curl -fsSL "$SKILL_URL" -o "$SKILL_DIR/SKILL.md"
    else
        say "Warning: curl is required to install the Hermes skill." >&2
    fi
else
    say "Hermes directory not found; skipping agent skill installation."
    say "Later, copy skill/SKILL.md to ~/.hermes/skills/nomnomcli/SKILL.md."
fi

say "nomnomcli installation complete."
say "Next: run 'nomnom setup' in an interactive terminal before the first food log."
say "Then verify provider readiness with 'nomnom doctor --json'."
