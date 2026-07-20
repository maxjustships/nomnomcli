from __future__ import annotations

import json
import os
import tempfile
import tomllib
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from nomnomcli.errors import NomnomError

USDA_ENV_VAR = "NOMNOM_USDA_KEY"


@dataclass(frozen=True, slots=True)
class Credential:
    value: str
    source: str


class ProviderConfig:
    """Read and persist provider settings outside the repository and user database."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        self._environ = os.environ if environ is None else environ
        self._config_path = Path(config_path).expanduser() if config_path else None

    @property
    def path(self) -> Path:
        if self._config_path is not None:
            return self._config_path
        root = self._environ.get("XDG_CONFIG_HOME")
        base = Path(root).expanduser() if root else Path.home() / ".config"
        return base / "nomnomcli" / "config.toml"

    def usda_credential(self) -> Credential | None:
        environment_key = self._environ.get(USDA_ENV_VAR, "").strip()
        if environment_key:
            return Credential(environment_key, "environment")
        stored_key = self._stored_usda_key()
        return Credential(stored_key, "user_config") if stored_key else None

    def _stored_usda_key(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            payload = tomllib.loads(self.path.read_text(encoding="utf-8"))
            value = payload.get("providers", {}).get("usda", {}).get("api_key")
        except (OSError, tomllib.TOMLDecodeError, AttributeError) as exc:
            raise NomnomError(
                "provider_config_invalid",
                f"Provider configuration is invalid: {self.path}",
                details={"path": str(self.path), "action": "Run nomnom setup again"},
            ) from exc
        if value is None:
            return None
        if not isinstance(value, str):
            raise NomnomError(
                "provider_config_invalid",
                "USDA api_key in provider configuration must be a string",
                details={"path": str(self.path), "action": "Run nomnom setup again"},
            )
        return value.strip() or None

    def store_usda_key(self, api_key: str) -> Path:
        key = api_key.strip()
        if not key or any(ord(character) < 32 for character in key):
            raise NomnomError("usda_key_invalid", "USDA API key must not be empty")

        destination = self.path
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            destination.parent.chmod(0o700)
        content = f"[providers.usda]\napi_key = {json.dumps(key, ensure_ascii=False)}\n"
        temporary_name: str | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".config.toml.", dir=destination.parent
            )
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, destination)
            temporary_name = None
            destination.chmod(0o600)
        except OSError as exc:
            raise NomnomError(
                "provider_config_write_failed",
                f"Could not securely write provider configuration: {destination}",
                details={"path": str(destination)},
            ) from exc
        finally:
            if temporary_name is not None:
                with suppress(FileNotFoundError):
                    Path(temporary_name).unlink()
        return destination
