from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from nomnomcli.db import _copy_stable_database_snapshot, _open_snapshot_source_path
from nomnomcli.errors import NomnomError


def _error_result(error: NomnomError) -> dict[str, object]:
    return {"ok": False, "error": error.as_dict()["error"]}


def _helper_failure(message: str) -> NomnomError:
    return NomnomError(
        "database_snapshot_helper_failed",
        message,
        details={
            "would_write": False,
            "action": "Retry resolution with a valid local database path.",
        },
    )


def _read_request() -> tuple[Path, Path]:
    try:
        request = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise _helper_failure("The isolated SQLite snapshot request is invalid") from error
    if not isinstance(request, dict):
        raise _helper_failure("The isolated SQLite snapshot request is invalid")
    source_path = request.get("source_path")
    private_root = request.get("private_root")
    if not isinstance(source_path, str) or not isinstance(private_root, str):
        raise _helper_failure("The isolated SQLite snapshot request is invalid")
    return Path(source_path), Path(private_root)


def main() -> int:
    try:
        source_path, private_root = _read_request()
        with _open_snapshot_source_path(source_path) as source:
            private_path = (
                _copy_stable_database_snapshot(source, private_root)
                if source is not None
                else None
            )
        snapshot = (
            os.fspath(private_path.relative_to(private_root))
            if private_path is not None
            else None
        )
        result: dict[str, object] = {"ok": True, "snapshot": snapshot}
    except NomnomError as error:
        result = _error_result(error)
    except Exception:
        result = _error_result(
            _helper_failure("The isolated SQLite snapshot helper failed unexpectedly")
        )
    json.dump(result, sys.stdout, allow_nan=False, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
