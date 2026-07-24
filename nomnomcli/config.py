from __future__ import annotations

import json
import os
import tempfile
import tomllib
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from nomnomcli.accuracy import (
    ACCURACY_PROFILES,
    DEFAULT_ACCURACY_PROFILE,
    profile_spec,
    validate_accuracy_profile,
)
from nomnomcli.errors import NomnomError
from nomnomcli.portions import DEFAULT_PORTION_POLICY, validate_portion_policy

USDA_ENV_VAR = "NOMNOM_USDA_KEY"
ACCURACY_PROFILE_ENV_VAR = "NOMNOM_ACCURACY_PROFILE"
GENERIC_PROXY_POLICY_ENV_VAR = "NOMNOM_GENERIC_PROXY_POLICY"
GENERIC_PROXY_POLICIES = (
    "allow_for_unbranded",
    "ask",
    "exact_only",
)
DEFAULT_GENERIC_PROXY_POLICY = "allow_for_unbranded"
PORTION_POLICY_ENV_VAR = "NOMNOM_PORTION_POLICY"


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

    def generic_proxy_policy(self) -> str:
        environment_policy = self._environ.get(GENERIC_PROXY_POLICY_ENV_VAR, "").strip()
        if environment_policy:
            return self._validate_generic_proxy_policy(environment_policy, "environment")
        payload = self._stored_payload()
        try:
            stored_policy = payload.get("resolution", {}).get("generic_proxy_policy")
        except AttributeError as exc:
            raise self._invalid_config_error() from exc
        if stored_policy is None:
            return DEFAULT_GENERIC_PROXY_POLICY
        if not isinstance(stored_policy, str):
            raise NomnomError(
                "generic_proxy_policy_invalid",
                "generic_proxy_policy in provider configuration must be a string",
                details={"path": str(self.path), "allowed": list(GENERIC_PROXY_POLICIES)},
            )
        return self._validate_generic_proxy_policy(stored_policy, "user_config")

    def accuracy_profile(self) -> str:
        environment_profile = self._environ.get(ACCURACY_PROFILE_ENV_VAR, "").strip()
        if environment_profile:
            return self._validate_accuracy_profile(environment_profile, "environment")
        payload = self._stored_payload()
        try:
            stored_profile = payload.get("resolution", {}).get("accuracy_profile")
        except AttributeError as exc:
            raise self._invalid_config_error() from exc
        if stored_profile is None:
            return DEFAULT_ACCURACY_PROFILE
        if not isinstance(stored_profile, str):
            raise NomnomError(
                "accuracy_profile_invalid",
                "accuracy_profile in provider configuration must be a string",
                details={"path": str(self.path), "allowed": list(ACCURACY_PROFILES)},
            )
        return self._validate_accuracy_profile(stored_profile, "user_config")

    def portion_policy(self) -> str:
        environment_policy = self._environ.get(PORTION_POLICY_ENV_VAR, "").strip()
        if environment_policy:
            return validate_portion_policy(environment_policy, source="environment")
        payload = self._stored_payload()
        try:
            stored_policy = payload.get("resolution", {}).get("portion_policy")
        except AttributeError as exc:
            raise self._invalid_config_error() from exc
        if stored_policy is None:
            explicit_profile = self._explicit_accuracy_profile(payload)
            if explicit_profile is not None:
                return profile_spec(explicit_profile).default_portion_policy
            return DEFAULT_PORTION_POLICY
        if not isinstance(stored_policy, str):
            raise NomnomError(
                "portion_policy_invalid",
                "portion_policy in provider configuration must be a string",
                details={"path": str(self.path)},
            )
        return validate_portion_policy(stored_policy, source="user_config")

    def _validate_generic_proxy_policy(self, value: str, source: str) -> str:
        policy = value.strip()
        if policy not in GENERIC_PROXY_POLICIES:
            raise NomnomError(
                "generic_proxy_policy_invalid",
                f"Unsupported generic proxy policy: {policy or '(empty)'}",
                details={
                    "source": source,
                    "allowed": list(GENERIC_PROXY_POLICIES),
                    "environment_variable": GENERIC_PROXY_POLICY_ENV_VAR,
                    "path": str(self.path),
                },
            )
        return policy

    def _validate_accuracy_profile(self, value: str, source: str) -> str:
        try:
            return validate_accuracy_profile(value, source=source, path=str(self.path))
        except NomnomError as exc:
            exc.details["environment_variable"] = ACCURACY_PROFILE_ENV_VAR
            raise

    def _explicit_accuracy_profile(self, payload: dict | None = None) -> str | None:
        environment_profile = self._environ.get(ACCURACY_PROFILE_ENV_VAR, "").strip()
        if environment_profile:
            return self._validate_accuracy_profile(environment_profile, "environment")
        stored = payload if payload is not None else self._stored_payload()
        try:
            value = stored.get("resolution", {}).get("accuracy_profile")
        except AttributeError as exc:
            raise self._invalid_config_error() from exc
        if value is None:
            return None
        if not isinstance(value, str):
            raise NomnomError(
                "accuracy_profile_invalid",
                "accuracy_profile in provider configuration must be a string",
                details={"path": str(self.path), "allowed": list(ACCURACY_PROFILES)},
            )
        return self._validate_accuracy_profile(value, "user_config")

    def _invalid_config_error(self) -> NomnomError:
        return NomnomError(
            "provider_config_invalid",
            f"Provider configuration is invalid: {self.path}",
            details={"path": str(self.path), "action": "Run nomnom setup again"},
        )

    def _stored_payload(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            payload = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise self._invalid_config_error() from exc
        if not isinstance(payload, dict):
            raise self._invalid_config_error()
        return payload

    def _stored_usda_key(self) -> str | None:
        try:
            payload = self._stored_payload()
            value = payload.get("providers", {}).get("usda", {}).get("api_key")
        except AttributeError as exc:
            raise self._invalid_config_error() from exc
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

        payload = self._stored_payload()
        try:
            stored_policy = payload.get("resolution", {}).get("generic_proxy_policy")
            stored_portion_policy = payload.get("resolution", {}).get("portion_policy")
            stored_accuracy_profile = payload.get("resolution", {}).get("accuracy_profile")
        except AttributeError as exc:
            raise self._invalid_config_error() from exc
        if stored_policy is not None and not isinstance(stored_policy, str):
            raise NomnomError(
                "generic_proxy_policy_invalid",
                "generic_proxy_policy in provider configuration must be a string",
                details={"path": str(self.path), "allowed": list(GENERIC_PROXY_POLICIES)},
            )
        policy = (
            self._validate_generic_proxy_policy(stored_policy, "user_config")
            if stored_policy is not None
            else None
        )
        if stored_portion_policy is not None and not isinstance(stored_portion_policy, str):
            raise NomnomError(
                "portion_policy_invalid",
                "portion_policy in provider configuration must be a string",
                details={"path": str(self.path)},
            )
        portion_policy = (
            validate_portion_policy(stored_portion_policy, source="user_config")
            if stored_portion_policy is not None
            else None
        )
        if stored_accuracy_profile is not None and not isinstance(
            stored_accuracy_profile, str
        ):
            raise NomnomError(
                "accuracy_profile_invalid",
                "accuracy_profile in provider configuration must be a string",
                details={"path": str(self.path), "allowed": list(ACCURACY_PROFILES)},
            )
        accuracy_profile = (
            self._validate_accuracy_profile(stored_accuracy_profile, "user_config")
            if stored_accuracy_profile is not None
            else None
        )
        content = f"[providers.usda]\napi_key = {json.dumps(key, ensure_ascii=False)}\n"
        content += self._resolution_content(
            generic_proxy_policy=policy,
            portion_policy=portion_policy,
            accuracy_profile=accuracy_profile,
        )
        return self._secure_write(content)

    def store_accuracy_profile(self, profile: str) -> Path:
        accuracy_profile = self._validate_accuracy_profile(profile, "command_line")
        payload = self._stored_payload()
        try:
            api_key = payload.get("providers", {}).get("usda", {}).get("api_key")
            stored_policy = payload.get("resolution", {}).get("generic_proxy_policy")
            stored_portion_policy = payload.get("resolution", {}).get("portion_policy")
        except AttributeError as exc:
            raise self._invalid_config_error() from exc
        if api_key is not None and not isinstance(api_key, str):
            raise self._invalid_config_error()
        policy = (
            self._validate_generic_proxy_policy(stored_policy, "user_config")
            if isinstance(stored_policy, str)
            else None
        )
        if stored_policy is not None and not isinstance(stored_policy, str):
            raise self._invalid_config_error()
        portion_policy = (
            validate_portion_policy(stored_portion_policy, source="user_config")
            if isinstance(stored_portion_policy, str)
            else None
        )
        if stored_portion_policy is not None and not isinstance(stored_portion_policy, str):
            raise self._invalid_config_error()
        content = ""
        if api_key:
            content = (
                "[providers.usda]\n"
                f"api_key = {json.dumps(api_key.strip(), ensure_ascii=False)}\n"
            )
        content += self._resolution_content(
            generic_proxy_policy=policy,
            portion_policy=portion_policy,
            accuracy_profile=accuracy_profile,
        )
        return self._secure_write(content)

    def _resolution_content(
        self,
        *,
        generic_proxy_policy: str | None,
        portion_policy: str | None,
        accuracy_profile: str | None,
    ) -> str:
        values = {
            "accuracy_profile": accuracy_profile,
            "generic_proxy_policy": generic_proxy_policy,
            "portion_policy": portion_policy,
        }
        present = {key: value for key, value in values.items() if value is not None}
        if not present:
            return ""
        content = "\n[resolution]\n"
        for key, value in present.items():
            content += f"{key} = {json.dumps(value, ensure_ascii=False)}\n"
        return content

    def _secure_write(self, content: str) -> Path:
        destination = self.path
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            destination.parent.chmod(0o700)
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
