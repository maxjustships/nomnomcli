from __future__ import annotations

import errno
import json
import os
import shutil
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from nomnomcli.errors import NomnomError, require_finite_numbers

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised through the support predicate
    _fcntl = None

LATEST_SCHEMA_VERSION = 4
V1_TABLES = frozenset({"food_cache", "log_entries", "recipes"})
_SNAPSHOT_SUFFIXES = ("", "-journal", "-wal", "-shm")
_SNAPSHOT_COPY_ATTEMPTS = 3
_SNAPSHOT_HELPER_TIMEOUT_SECONDS = 10.0
_SNAPSHOT_HELPER_BOOTSTRAP = """\
import runpy
import sys

trusted_root, helper_path = sys.argv[1:]
sys.path.insert(0, trusted_root)
runpy.run_path(helper_path, run_name="__main__")
"""
_SQLITE_LOCK_BYTE = 0x40000000
_SQLITE_LOCK_BYTE_COUNT = 512
_SQLITE_SHM_LOCK_OFFSET = 120
_SQLITE_SHM_LOCK_COUNT = 8
_LINUX_F_OFD_SETLK = 37
_LINUX_FLOCK = struct.Struct("@hh4xqqi4x")
_NOATIME_UNAVAILABLE_ERRNOS = frozenset(
    {
        errno.EPERM,
        errno.EINVAL,
        errno.EOPNOTSUPP,
        errno.ENOTSUP,
    }
)

LATEST_SCHEMA = (
    """CREATE TABLE food_cache (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    kcal REAL NOT NULL,
    protein REAL NOT NULL,
    fat REAL NOT NULL,
    carbs REAL NOT NULL,
    piece_grams REAL,
    density_g_ml REAL,
    source TEXT NOT NULL,
    fdc_id INTEGER,
    barcode TEXT,
    brand TEXT,
    lookup_query TEXT,
    alternatives_json TEXT,
    piece_grams_source TEXT,
    piece_grams_source_value TEXT,
    resolution_mode TEXT NOT NULL DEFAULT 'legacy',
    source_id TEXT,
    source_note TEXT,
    provenance TEXT,
    assumption TEXT
)""",
    """CREATE TABLE log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'food',
    label TEXT,
    items_json TEXT NOT NULL,
    kcal REAL NOT NULL,
    protein REAL NOT NULL,
    fat REAL NOT NULL,
    carbs REAL NOT NULL
)""",
    "CREATE INDEX idx_log_entries_logged_at ON log_entries(logged_at)",
    """CREATE TABLE recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    source_url TEXT NOT NULL,
    servings REAL NOT NULL,
    ingredients_json TEXT NOT NULL,
    kcal_per_serving REAL NOT NULL,
    protein_per_serving REAL NOT NULL,
    fat_per_serving REAL NOT NULL,
    carbs_per_serving REAL NOT NULL,
    created_at TEXT NOT NULL
    )""",
    """CREATE TABLE food_aliases (
    phrase TEXT NOT NULL,
    normalized_phrase TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL COLLATE NOCASE
)""",
)

_REQUIRED_CURRENT_SCHEMA_COLUMNS = {
    "food_cache": frozenset(
        {
            "name",
            "kcal",
            "protein",
            "fat",
            "carbs",
            "piece_grams",
            "density_g_ml",
            "source",
            "fdc_id",
            "barcode",
            "brand",
            "lookup_query",
            "alternatives_json",
            "piece_grams_source",
            "piece_grams_source_value",
            "resolution_mode",
            "source_id",
            "source_note",
            "provenance",
            "assumption",
        }
    ),
    "log_entries": frozenset(
        {
            "id",
            "logged_at",
            "kind",
            "label",
            "items_json",
            "kcal",
            "protein",
            "fat",
            "carbs",
        }
    ),
    "recipes": frozenset(
        {
            "id",
            "name",
            "source_url",
            "servings",
            "ingredients_json",
            "kcal_per_serving",
            "protein_per_serving",
            "fat_per_serving",
            "carbs_per_serving",
            "created_at",
        }
    ),
    "food_aliases": frozenset(
        {"phrase", "normalized_phrase", "canonical_name"}
    ),
}
_REQUIRED_CURRENT_SCHEMA_INDEXES = {
    "idx_log_entries_logged_at": ("log_entries", ("logged_at",)),
}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def _set_user_version(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(f"PRAGMA user_version = {version}")


def _validate_current_schema(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version != LATEST_SCHEMA_VERSION:
        raise sqlite3.DatabaseError(
            f"database schema version {version} is not current version "
            f"{LATEST_SCHEMA_VERSION}"
        )

    integrity = connection.execute("PRAGMA quick_check").fetchall()
    if len(integrity) != 1 or str(integrity[0][0]).casefold() != "ok":
        raise sqlite3.DatabaseError("database integrity check failed")

    tables = _table_names(connection)
    missing_tables = _REQUIRED_CURRENT_SCHEMA_COLUMNS.keys() - tables
    if missing_tables:
        raise sqlite3.DatabaseError(
            "current schema is missing tables: " + ", ".join(sorted(missing_tables))
        )
    for table, required_columns in _REQUIRED_CURRENT_SCHEMA_COLUMNS.items():
        missing_columns = required_columns - _column_names(connection, table)
        if missing_columns:
            raise sqlite3.DatabaseError(
                f"current schema table {table} is missing columns: "
                + ", ".join(sorted(missing_columns))
            )

    indexes = {
        str(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    for index, (table, required_columns) in _REQUIRED_CURRENT_SCHEMA_INDEXES.items():
        if indexes.get(index) != table:
            raise sqlite3.DatabaseError(
                f"current schema is missing index {index} on table {table}"
            )
        columns = tuple(
            str(row[2]) for row in connection.execute(f"PRAGMA index_info({index})")
        )
        if columns != required_columns:
            raise sqlite3.DatabaseError(
                f"current schema index {index} has unexpected columns"
            )


def _ensure_required_current_indexes(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_log_entries_logged_at "
        "ON log_entries(logged_at)"
    )


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    if "food_cache" not in _table_names(connection):
        raise sqlite3.DatabaseError("schema v1 is missing the food_cache table")
    columns = _column_names(connection, "food_cache")
    additions = {
        "barcode": "ALTER TABLE food_cache ADD COLUMN barcode TEXT",
        "brand": "ALTER TABLE food_cache ADD COLUMN brand TEXT",
        "lookup_query": "ALTER TABLE food_cache ADD COLUMN lookup_query TEXT",
        "alternatives_json": "ALTER TABLE food_cache ADD COLUMN alternatives_json TEXT",
    }
    for column, statement in additions.items():
        if column not in columns:
            connection.execute(statement)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_food_cache_lookup_query "
        "ON food_cache(lookup_query COLLATE NOCASE)"
    )


def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS food_aliases (
        phrase TEXT NOT NULL,
        normalized_phrase TEXT PRIMARY KEY,
        canonical_name TEXT NOT NULL COLLATE NOCASE
    )"""
    )


def _ensure_v4_food_cache(connection: sqlite3.Connection) -> None:
    columns = _column_names(connection, "food_cache")
    additions = {
        "piece_grams_source": "ALTER TABLE food_cache ADD COLUMN piece_grams_source TEXT",
        "piece_grams_source_value": (
            "ALTER TABLE food_cache ADD COLUMN piece_grams_source_value TEXT"
        ),
        "resolution_mode": (
            "ALTER TABLE food_cache ADD COLUMN resolution_mode "
            "TEXT NOT NULL DEFAULT 'legacy'"
        ),
        "source_id": "ALTER TABLE food_cache ADD COLUMN source_id TEXT",
        "source_note": "ALTER TABLE food_cache ADD COLUMN source_note TEXT",
        "provenance": "ALTER TABLE food_cache ADD COLUMN provenance TEXT",
        "assumption": "ALTER TABLE food_cache ADD COLUMN assumption TEXT",
    }
    for column, statement in additions.items():
        if column not in columns:
            connection.execute(statement)
    connection.execute(
        """UPDATE food_cache
        SET source_id = COALESCE(barcode, CAST(fdc_id AS TEXT))
        WHERE source_id IS NULL"""
    )
    connection.execute(
        "UPDATE food_cache SET provenance = source WHERE provenance IS NULL"
    )


def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    _ensure_v4_food_cache(connection)


MIGRATIONS = {1: _migrate_v1_to_v2, 2: _migrate_v2_to_v3, 3: _migrate_v3_to_v4}


def _initialize_database(
    connection: sqlite3.Connection, *, reject_incomplete_current: bool = False
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > LATEST_SCHEMA_VERSION:
            raise sqlite3.DatabaseError(
                f"database schema version {version} is newer than supported "
                f"version {LATEST_SCHEMA_VERSION}"
            )

        if reject_incomplete_current and version == LATEST_SCHEMA_VERSION:
            _validate_current_schema(connection)

        if version == 0 and _table_names(connection) & V1_TABLES:
            version = 1
            _set_user_version(connection, version)

        if version == 0:
            for statement in LATEST_SCHEMA:
                connection.execute(statement)
            _set_user_version(connection, LATEST_SCHEMA_VERSION)
        else:
            while version < LATEST_SCHEMA_VERSION:
                MIGRATIONS[version](connection)
                version += 1
                _set_user_version(connection, version)
            missing = V1_TABLES - _table_names(connection)
            for statement in LATEST_SCHEMA:
                if "TABLE " not in statement:
                    continue
                table = statement.split("TABLE ", 1)[1].split(" ", 1)[0].strip().strip("(")
                if table in missing:
                    connection.execute(statement)
        if "food_cache" in _table_names(connection):
            _ensure_v4_food_cache(connection)
        _ensure_required_current_indexes(connection)
        if reject_incomplete_current:
            _validate_current_schema(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def default_db_path() -> Path:
    override = os.getenv("NOMNOM_DB_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "nomnomcli" / "nomnom.sqlite3"


def _ofd_locks_supported() -> bool:
    """Return whether this runtime has the Linux lock ABI used by SQLite's unix VFS."""
    return (
        sys.platform.startswith("linux")
        and struct.calcsize("P") == 8
        and _fcntl is not None
        and _LINUX_FLOCK.size == 32
    )


def _snapshot_lock_error(code: str, message: str, **details: object) -> NomnomError:
    return NomnomError(
        code,
        message,
        details={
            "would_write": False,
            **details,
        },
    )


def _snapshot_read_error(suffix: str, error: OSError) -> NomnomError:
    target = suffix.removeprefix("-") or "main"
    return _snapshot_lock_error(
        "database_snapshot_unreadable",
        "A SQLite source file cannot be read for a no-write snapshot",
        snapshot_target=target,
        os_error=error.errno,
        action="Restore read access to the database and its SQLite sidecar files.",
    )


def _snapshot_noatime_error(suffix: str, error: OSError | None = None) -> NomnomError:
    target = suffix.removeprefix("-") or "main"
    details: dict[str, object] = {
        "snapshot_target": target,
        "action": (
            "Run resolution as the owner of every SQLite source file, or copy the "
            "database and its sidecars to a Linux filesystem you own that supports "
            "O_NOATIME."
        ),
    }
    if error is not None:
        details["os_error"] = error.errno
    return _snapshot_lock_error(
        "database_snapshot_noatime_unavailable",
        "A SQLite source file cannot be read without updating its access time",
        **details,
    )


def _snapshot_unsafe_path_error(
    component: str, *, suffix: str = "", parent: bool = False
) -> NomnomError:
    return _snapshot_lock_error(
        "database_snapshot_unsafe_path",
        "SQLite snapshot paths must not contain symbolic links",
        snapshot_target="parent" if parent else suffix.removeprefix("-") or "main",
        path_component=component,
        action="Use a database path whose parent directories and SQLite files are not symlinks.",
    )


def _snapshot_file_type(mode: int) -> str:
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISCHR(mode):
        return "character_device"
    if stat.S_ISBLK(mode):
        return "block_device"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISDIR(mode):
        return "directory"
    return "non_regular"


def _snapshot_unsafe_file_type_error(suffix: str, mode: int) -> NomnomError:
    return _snapshot_lock_error(
        "database_snapshot_unsafe_file_type",
        "SQLite snapshot sources must be ordinary regular files",
        snapshot_target=suffix.removeprefix("-") or "main",
        file_type=_snapshot_file_type(mode),
        action=(
            "Use a regular file for the database and every existing SQLite "
            "journal, WAL, or SHM sidecar, then retry resolution."
        ),
    )


def _snapshot_invalid_database_error() -> NomnomError:
    return _snapshot_lock_error(
        "database_snapshot_invalid",
        "The SQLite source is not a valid supported database",
        snapshot_target="main",
        action=(
            "Replace the source with a valid SQLite database supported by this "
            "nomnomcli version, or move it aside and retry with an empty database."
        ),
    )


def _snapshot_unstable_path_error() -> NomnomError:
    return _snapshot_lock_error(
        "database_snapshot_unstable",
        "Database path changed while creating a read-only snapshot",
        attempts=_SNAPSHOT_COPY_ATTEMPTS,
        action="Wait for database path changes to finish, then retry resolution.",
    )


def _snapshot_helper_error(
    code: str, message: str, **details: object
) -> NomnomError:
    return _snapshot_lock_error(
        code,
        message,
        action=(
            "Retry resolution; if the failure persists, verify the local Python "
            "installation and database filesystem."
        ),
        **details,
    )


def _trusted_snapshot_helper_command() -> tuple[list[str], Path]:
    try:
        package_directory = Path(__file__).resolve(strict=True).parent
        helper_path = (package_directory / "_snapshot_helper.py").resolve(strict=True)
        helper_metadata = helper_path.stat()
    except OSError as error:
        raise _snapshot_helper_error(
            "database_snapshot_helper_failed",
            "The trusted isolated SQLite snapshot helper is unavailable",
            os_error=error.errno,
        ) from error

    if helper_path.parent != package_directory or not stat.S_ISREG(
        helper_metadata.st_mode
    ):
        raise _snapshot_helper_error(
            "database_snapshot_helper_failed",
            "The trusted isolated SQLite snapshot helper is unavailable",
        )

    trusted_package_root = package_directory.parent
    return (
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            _SNAPSHOT_HELPER_BOOTSTRAP,
            os.fspath(trusted_package_root),
            os.fspath(helper_path),
        ],
        trusted_package_root,
    )


def _run_snapshot_helper(source_path: Path, private_root: Path) -> Path | None:
    """Acquire a source snapshot in a fresh exec process with no inherited DB FDs."""
    request = json.dumps(
        {"source_path": os.fspath(source_path), "private_root": os.fspath(private_root)},
        allow_nan=False,
    )
    command, trusted_package_root = _trusted_snapshot_helper_command()
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    try:
        completed = subprocess.run(
            command,
            input=request,
            capture_output=True,
            check=False,
            close_fds=True,
            cwd=trusted_package_root,
            env=environment,
            text=True,
            timeout=_SNAPSHOT_HELPER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise _snapshot_helper_error(
            "database_snapshot_timeout",
            "The isolated SQLite snapshot helper timed out",
            timeout_seconds=_SNAPSHOT_HELPER_TIMEOUT_SECONDS,
        ) from error
    except OSError as error:
        raise _snapshot_helper_error(
            "database_snapshot_helper_failed",
            "The isolated SQLite snapshot helper could not start",
            os_error=error.errno,
        ) from error

    if completed.returncode != 0:
        raise _snapshot_helper_error(
            "database_snapshot_helper_failed",
            "The isolated SQLite snapshot helper exited unexpectedly",
            process_returncode=completed.returncode,
        )
    try:
        result = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise _snapshot_helper_error(
            "database_snapshot_helper_failed",
            "The isolated SQLite snapshot helper returned an invalid response",
        ) from error
    if not isinstance(result, dict) or type(result.get("ok")) is not bool:
        raise _snapshot_helper_error(
            "database_snapshot_helper_failed",
            "The isolated SQLite snapshot helper returned an invalid response",
        )
    if result["ok"] is False:
        serialized_error = result.get("error")
        if not isinstance(serialized_error, dict):
            raise _snapshot_helper_error(
                "database_snapshot_helper_failed",
                "The isolated SQLite snapshot helper returned an invalid error",
            )
        code = serialized_error.get("code")
        message = serialized_error.get("message")
        details = serialized_error.get("details", {})
        if not isinstance(code, str) or not isinstance(message, str) or not isinstance(
            details, dict
        ):
            raise _snapshot_helper_error(
                "database_snapshot_helper_failed",
                "The isolated SQLite snapshot helper returned an invalid error",
            )
        raise NomnomError(code, message, details=details)

    snapshot = result.get("snapshot")
    if snapshot is None:
        return None
    if not isinstance(snapshot, str):
        raise _snapshot_helper_error(
            "database_snapshot_helper_failed",
            "The isolated SQLite snapshot helper returned an invalid path",
        )
    relative_path = Path(snapshot)
    parts = relative_path.parts
    valid_attempt = (
        len(parts) == 2
        and parts[0].startswith("attempt-")
        and parts[0][len("attempt-") :].isdigit()
        and 1 <= int(parts[0][len("attempt-") :]) <= _SNAPSHOT_COPY_ATTEMPTS
        and parts[1] == "snapshot.sqlite3"
    )
    if relative_path.is_absolute() or not valid_attempt:
        raise _snapshot_helper_error(
            "database_snapshot_helper_failed",
            "The isolated SQLite snapshot helper returned an unsafe path",
        )
    private_path = private_root / relative_path
    try:
        metadata = private_path.lstat()
    except OSError as error:
        raise _snapshot_helper_error(
            "database_snapshot_helper_failed",
            "The isolated SQLite snapshot helper did not create its snapshot",
            os_error=error.errno,
        ) from error
    if not stat.S_ISREG(metadata.st_mode):
        raise _snapshot_helper_error(
            "database_snapshot_helper_failed",
            "The isolated SQLite snapshot helper returned a non-regular path",
        )
    return private_path


def _snapshot_open_capabilities() -> tuple[int, int, int, int]:
    if not sys.platform.startswith("linux") or not _ofd_locks_supported():
        raise _snapshot_lock_error(
            "database_snapshot_lock_unavailable",
            "A compatible no-write SQLite snapshot lock is unavailable",
            action="Run resolution on a supported 64-bit Linux filesystem/runtime.",
        )

    noatime = getattr(os, "O_NOATIME", None)
    if noatime is None:
        raise _snapshot_noatime_error("")

    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    path_only = getattr(os, "O_PATH", None)
    missing = [
        name
        for name, value in (
            ("O_NOFOLLOW", nofollow),
            ("O_DIRECTORY", directory),
            ("O_PATH", path_only),
        )
        if value is None
    ]
    if missing:
        raise _snapshot_lock_error(
            "database_snapshot_lock_unavailable",
            "The runtime cannot safely open a no-write SQLite snapshot",
            missing_capabilities=missing,
            action="Run resolution on a supported 64-bit Linux filesystem/runtime.",
        )
    return noatime, nofollow, directory, path_only


def _snapshot_directory_flags() -> int:
    _, nofollow, directory, path_only = _snapshot_open_capabilities()
    # O_PATH obtains only a reference to the directory inode: it does not open
    # the directory for data access and therefore does not require ownership to
    # suppress atime updates on root-owned ancestors.
    return path_only | os.O_CLOEXEC | nofollow | directory


def _descriptor_identity(file_descriptor: int) -> tuple[int, int]:
    metadata = os.fstat(file_descriptor)
    return metadata.st_dev, metadata.st_ino


def _open_snapshot_directory(
    component: str, *, directory_descriptor: int | None = None
) -> int:
    try:
        if directory_descriptor is None:
            return os.open(component, _snapshot_directory_flags())
        return os.open(
            component,
            _snapshot_directory_flags(),
            dir_fd=directory_descriptor,
        )
    except OSError as error:
        if error.errno == errno.ENOENT:
            raise
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise _snapshot_unsafe_path_error(component, parent=True) from error
        raise _snapshot_lock_error(
            "database_snapshot_unreadable",
            "A database parent directory cannot be opened safely",
            snapshot_target="parent",
            path_component=component,
            os_error=error.errno,
            action="Restore access to a non-symlink database parent directory.",
        ) from error


@dataclass(slots=True)
class _SnapshotSource:
    directory_descriptor: int
    filename: str
    parent_chain: tuple[tuple[int, str, tuple[int, int]], ...]

    def validate_parent_chain(self) -> None:
        """Prove every retained parent still names the directory inode we opened."""
        for parent_descriptor, component, expected in self.parent_chain:
            try:
                descriptor = _open_snapshot_directory(
                    component, directory_descriptor=parent_descriptor
                )
            except FileNotFoundError as error:
                raise _snapshot_unstable_path_error() from error
            except NomnomError as error:
                if error.code == "database_snapshot_unreadable":
                    raise _snapshot_unstable_path_error() from error
                raise
            try:
                if _descriptor_identity(descriptor) != expected:
                    raise _snapshot_unstable_path_error()
            finally:
                os.close(descriptor)

    def validate_absent_child(self, component: str) -> None:
        """Confirm absence relative to the retained parent around chain validation."""
        self.validate_parent_chain()
        try:
            descriptor = _open_snapshot_directory(
                component, directory_descriptor=self.directory_descriptor
            )
        except FileNotFoundError:
            pass
        else:
            os.close(descriptor)
            raise _snapshot_unstable_path_error()
        self.validate_parent_chain()


@contextmanager
def _open_snapshot_source_path(source_path: Path) -> Iterator[_SnapshotSource | None]:
    """Walk a Linux path without following or touching symlink metadata."""
    _snapshot_open_capabilities()
    components = list(source_path.parts)
    absolute = source_path.is_absolute()
    if absolute:
        components = components[1:]
    if not components or components[-1] in {"", ".", ".."}:
        raise _snapshot_unsafe_path_error(components[-1] if components else "")
    filename = components.pop()

    with ExitStack() as stack:
        current_descriptor = _open_snapshot_directory("/" if absolute else ".")
        stack.callback(os.close, current_descriptor)
        parent_chain: list[tuple[int, str, tuple[int, int]]] = []
        for component in components:
            if component in {"", "."}:
                continue
            try:
                child_descriptor = _open_snapshot_directory(
                    component, directory_descriptor=current_descriptor
                )
            except FileNotFoundError:
                absent_source = _SnapshotSource(
                    directory_descriptor=current_descriptor,
                    filename=filename,
                    parent_chain=tuple(parent_chain),
                )
                absent_source.validate_absent_child(component)
                yield None
                return
            stack.callback(os.close, child_descriptor)
            parent_chain.append(
                (current_descriptor, component, _descriptor_identity(child_descriptor))
            )
            current_descriptor = child_descriptor
        source = _SnapshotSource(
            directory_descriptor=current_descriptor,
            filename=filename,
            parent_chain=tuple(parent_chain),
        )
        source.validate_parent_chain()
        yield source


def _acquire_ofd_read_lock(file_descriptor: int, start: int, length: int, target: str) -> None:
    """Take a nonblocking Linux OFD lock that conflicts with SQLite POSIX writes."""
    if not _ofd_locks_supported():
        raise _snapshot_lock_error(
            "database_snapshot_lock_unavailable",
            "A compatible no-write SQLite snapshot lock is unavailable",
            lock_target=target,
            action="Run resolution on a supported 64-bit Linux filesystem/runtime.",
        )
    assert _fcntl is not None
    lock = _LINUX_FLOCK.pack(_fcntl.F_RDLCK, os.SEEK_SET, start, length, 0)
    try:
        _fcntl.fcntl(file_descriptor, _LINUX_F_OFD_SETLK, lock)
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EAGAIN}:
            raise _snapshot_lock_error(
                "database_snapshot_busy",
                "An active SQLite writer prevents a consistent read-only snapshot",
                lock_target=target,
                action="Wait for the active database write to finish, then retry resolution.",
            ) from error
        raise _snapshot_lock_error(
            "database_snapshot_lock_unavailable",
            "The filesystem cannot provide the required no-write SQLite snapshot lock",
            lock_target=target,
            os_error=error.errno,
            action="Move the database to a filesystem with Linux OFD lock support.",
        ) from error


def _reject_non_regular_snapshot_path_after_open_error(
    source: _SnapshotSource, filename: str, suffix: str
) -> None:
    """Classify file types such as sockets/devices that cannot be read-opened."""
    noatime, nofollow, _, path_only = _snapshot_open_capabilities()
    flags = path_only | os.O_CLOEXEC | os.O_NONBLOCK | nofollow | noatime
    try:
        descriptor = os.open(filename, flags, dir_fd=source.directory_descriptor)
    except OSError:
        return
    try:
        metadata = os.fstat(descriptor)
    except OSError:
        return
    finally:
        os.close(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise _snapshot_unsafe_file_type_error(suffix, metadata.st_mode)


def _open_snapshot_source(source: _SnapshotSource, suffix: str) -> int:
    noatime, nofollow, _, _ = _snapshot_open_capabilities()
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | nofollow | noatime
    filename = f"{source.filename}{suffix}"
    try:
        descriptor = os.open(filename, flags, dir_fd=source.directory_descriptor)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise _snapshot_unsafe_path_error(filename, suffix=suffix) from error
        _reject_non_regular_snapshot_path_after_open_error(source, filename, suffix)
        if error.errno in _NOATIME_UNAVAILABLE_ERRNOS:
            raise _snapshot_noatime_error(suffix, error) from error
        raise
    try:
        metadata = os.fstat(descriptor)
    except OSError:
        os.close(descriptor)
        raise
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        raise _snapshot_unsafe_file_type_error(suffix, metadata.st_mode)
    return descriptor


def _source_snapshot_fingerprint(
    source_path: Path | _SnapshotSource,
) -> dict[str, tuple[int, int, int, int] | None]:
    """Capture source identity from no-follow/no-atime descriptors only."""
    if isinstance(source_path, Path):
        with _open_snapshot_source_path(source_path) as source:
            return _source_snapshot_fingerprint(source)

    fingerprint: dict[str, tuple[int, int, int, int] | None] = {}
    for suffix in _SNAPSHOT_SUFFIXES:
        try:
            descriptor = _open_snapshot_source(source_path, suffix)
        except FileNotFoundError:
            fingerprint[suffix] = None
            continue
        except OSError as error:
            raise _snapshot_read_error(suffix, error) from error
        try:
            fingerprint[suffix] = _descriptor_fingerprint(descriptor)
        finally:
            os.close(descriptor)
    return fingerprint


@contextmanager
def _sqlite_snapshot_boundary(
    source: _SnapshotSource,
) -> Iterator[tuple[int, int | None] | None]:
    """Freeze SQLite main-file writes and WAL coordination using OS locks only.

    Linux open-file-description locks conflict with SQLite's POSIX locks even
    inside one process and are not dropped when an unrelated descriptor closes.
    Locking the complete main lock-byte page rejects rollback writers (including
    MEMORY/OFF spill transactions); locking every SHM slot freezes WAL writers,
    checkpoints, and recovery. Other platforms fail closed before any copy.
    """
    try:
        main_descriptor = _open_snapshot_source(source, "")
    except FileNotFoundError:
        yield None
        return
    except OSError as error:
        raise _snapshot_lock_error(
            "database_snapshot_lock_unavailable",
            "The SQLite source cannot be opened for a no-write snapshot lock",
            lock_target="main",
            os_error=error.errno,
        ) from error

    shm_descriptor = None
    try:
        _acquire_ofd_read_lock(
            main_descriptor,
            _SQLITE_LOCK_BYTE,
            _SQLITE_LOCK_BYTE_COUNT,
            "main",
        )
        try:
            shm_descriptor = _open_snapshot_source(source, "-shm")
        except FileNotFoundError:
            pass
        except OSError as error:
            raise _snapshot_lock_error(
                "database_snapshot_lock_unavailable",
                "The SQLite SHM file cannot be opened for a no-write snapshot lock",
                lock_target="shm",
                os_error=error.errno,
            ) from error
        if shm_descriptor is not None:
            _acquire_ofd_read_lock(
                shm_descriptor,
                _SQLITE_SHM_LOCK_OFFSET,
                _SQLITE_SHM_LOCK_COUNT,
                "shm",
            )
        yield main_descriptor, shm_descriptor
    finally:
        if shm_descriptor is not None:
            os.close(shm_descriptor)
        os.close(main_descriptor)


def _descriptor_fingerprint(file_descriptor: int) -> tuple[int, int, int, int]:
    stat = os.fstat(file_descriptor)
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _copy_open_file(file_descriptor: int, destination: Path) -> None:
    """Copy the exact locked inode instead of reopening a path that could be replaced."""
    os.lseek(file_descriptor, 0, os.SEEK_SET)
    with destination.open("wb") as output:
        while chunk := os.read(file_descriptor, 1024 * 1024):
            output.write(chunk)


@contextmanager
def _open_snapshot_file_set(
    source: _SnapshotSource,
    fingerprint: dict[str, tuple[int, int, int, int] | None],
    locked_descriptors: tuple[int, int | None],
) -> Iterator[dict[str, int] | None]:
    """Open every fingerprinted source inode before accepting any source bytes."""
    main_descriptor, shm_descriptor = locked_descriptors
    descriptors = {"": main_descriptor}
    if shm_descriptor is not None:
        descriptors["-shm"] = shm_descriptor

    with ExitStack() as stack:
        for suffix in ("-journal", "-wal"):
            if fingerprint[suffix] is None:
                continue
            try:
                descriptor = _open_snapshot_source(source, suffix)
            except FileNotFoundError:
                yield None
                return
            except OSError as error:
                raise _snapshot_read_error(suffix, error) from error
            stack.callback(os.close, descriptor)
            descriptors[suffix] = descriptor
        yield descriptors


def _snapshot_descriptors_match(
    fingerprint: dict[str, tuple[int, int, int, int] | None],
    descriptors: dict[str, int],
) -> bool:
    for suffix, expected in fingerprint.items():
        descriptor = descriptors.get(suffix)
        if expected is None:
            if descriptor is not None:
                return False
        elif descriptor is None:
            return False
        else:
            try:
                actual = _descriptor_fingerprint(descriptor)
            except OSError as error:
                raise _snapshot_read_error(suffix, error) from error
            if expected != actual:
                return False
    return True


def _copy_stable_database_snapshot(
    source: _SnapshotSource, private_root: Path
) -> Path | None:
    """Copy a locked SQLite file set that remains unchanged across the complete copy."""
    for attempt in range(1, _SNAPSHOT_COPY_ATTEMPTS + 1):
        attempt_directory = private_root / f"attempt-{attempt}"
        attempt_directory.mkdir()
        private_path = attempt_directory / "snapshot.sqlite3"
        copy_succeeded = True
        source.validate_parent_chain()
        with _sqlite_snapshot_boundary(source) as descriptors:
            before = _source_snapshot_fingerprint(source)
            copied_suffix = ""
            try:
                if descriptors is None:
                    copy_succeeded = before[""] is None
                else:
                    with _open_snapshot_file_set(
                        source, before, descriptors
                    ) as source_descriptors:
                        copy_succeeded = (
                            source_descriptors is not None
                            and _snapshot_descriptors_match(before, source_descriptors)
                        )
                        if copy_succeeded:
                            for suffix in _SNAPSHOT_SUFFIXES:
                                descriptor = source_descriptors.get(suffix)
                                if descriptor is None:
                                    continue
                                copied_suffix = suffix
                                _copy_open_file(
                                    descriptor,
                                    Path(f"{private_path}{suffix}"),
                                )
            except FileNotFoundError:
                copy_succeeded = False
            except OSError as error:
                raise _snapshot_read_error(copied_suffix, error) from error
            after = _source_snapshot_fingerprint(source)
        source.validate_parent_chain()

        if copy_succeeded and before == after:
            return private_path if before[""] is not None else None
        shutil.rmtree(attempt_directory)

    raise _snapshot_unstable_path_error()


@contextmanager
def connect(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    db_path = Path(path) if path is not None else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.row_factory = sqlite3.Row
        _initialize_database(connection)
        yield connection
        connection.commit()
    finally:
        connection.close()


@contextmanager
def connect_read_only(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open a stable isolated snapshot, failing safely while source writes continue."""
    db_path = Path(path) if path is not None else default_db_path()
    connection = sqlite3.connect(":memory:")
    try:
        with tempfile.TemporaryDirectory(
            prefix="nomnomcli-read-only-"
        ) as temporary_directory:
            private_path = _run_snapshot_helper(db_path, Path(temporary_directory))
            if private_path is not None:
                try:
                    source = sqlite3.connect(private_path)
                    try:
                        source.backup(connection)
                    finally:
                        source.close()
                except sqlite3.ProgrammingError:
                    raise
                except sqlite3.DatabaseError as error:
                    raise _snapshot_invalid_database_error() from error

        connection.row_factory = sqlite3.Row
        # Validate and migrate only the in-memory snapshot. SQLite opens only a
        # private file set proven stable across copying, so concurrent churn
        # fails safely and source sidecars cannot be created or modified.
        if private_path is None:
            _initialize_database(connection, reject_incomplete_current=True)
        else:
            try:
                _initialize_database(connection, reject_incomplete_current=True)
            except sqlite3.ProgrammingError:
                raise
            except sqlite3.DatabaseError as error:
                raise _snapshot_invalid_database_error() from error
        connection.execute("PRAGMA query_only = ON")
        yield connection
    finally:
        connection.close()


def store_log(
    connection: sqlite3.Connection,
    items: list[dict],
    totals: dict[str, float],
    *,
    kind: str = "food",
    label: str | None = None,
    logged_at: datetime | None = None,
) -> int:
    timestamp = (logged_at or datetime.now().astimezone()).isoformat(timespec="seconds")
    require_finite_numbers((items, totals))
    cursor = connection.execute(
        """INSERT INTO log_entries
        (logged_at, kind, label, items_json, kcal, protein, fat, carbs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            timestamp,
            kind,
            label,
            json.dumps(items, ensure_ascii=False, sort_keys=True, allow_nan=False),
            totals["kcal"],
            totals["protein"],
            totals["fat"],
            totals["carbs"],
        ),
    )
    return int(cursor.lastrowid)


def period_start(period: str, now: datetime | None = None) -> datetime:
    current = now or datetime.now().astimezone()
    if period == "today":
        return current.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        today = current.replace(hour=0, minute=0, second=0, microsecond=0)
        return today - timedelta(days=today.weekday())
    raise ValueError(f"unsupported period: {period}")


def local_day_bounds(local_date: date) -> tuple[datetime, datetime]:
    next_date = local_date + timedelta(days=1)
    start = datetime(local_date.year, local_date.month, local_date.day).astimezone()
    end = datetime(next_date.year, next_date.month, next_date.day).astimezone()
    return start, end


def get_stats(
    connection: sqlite3.Connection,
    period: str,
    now: datetime | None = None,
    *,
    local_date: date | None = None,
) -> dict:
    end = None
    if period == "date":
        if local_date is None:
            raise ValueError("local_date is required for the date period")
        start, end = local_day_bounds(local_date)
        rows = connection.execute(
            """SELECT * FROM log_entries
            WHERE julianday(logged_at) >= julianday(?)
              AND julianday(logged_at) < julianday(?)
            ORDER BY logged_at, id""",
            (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")),
        ).fetchall()
    else:
        start = period_start(period, now)
        rows = connection.execute(
            "SELECT * FROM log_entries WHERE logged_at >= ? ORDER BY logged_at, id",
            (start.isoformat(timespec="seconds"),),
        ).fetchall()
    meals = []
    totals = {key: 0.0 for key in ("kcal", "protein", "fat", "carbs")}
    for row in rows:
        meal_totals = {key: round(float(row[key]), 2) for key in totals}
        for key, value in meal_totals.items():
            totals[key] += value
        items = json.loads(row["items_json"])
        require_finite_numbers((meal_totals, items))
        meals.append(
            {
                "id": row["id"],
                "logged_at": row["logged_at"],
                "kind": row["kind"],
                "label": row["label"],
                "items": items,
                "totals": meal_totals,
                "approximate": any(item.get("approximate") is True for item in items),
            }
        )
    result = {
        "period": period,
        "from": start.isoformat(timespec="seconds"),
        "totals": {key: round(value, 2) for key, value in totals.items()},
        "meals": meals,
        "approximate": any(meal["approximate"] for meal in meals),
    }
    if end is not None:
        result["to"] = end.isoformat(timespec="seconds")
        result["local_date"] = local_date.isoformat()
    require_finite_numbers(result)
    return result
