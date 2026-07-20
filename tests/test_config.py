from __future__ import annotations

import json
import stat

import pytest

from nomnomcli.config import ProviderConfig
from nomnomcli.errors import NomnomError
from nomnomcli.onboarding import doctor_report, setup_providers


class HealthyOFF:
    def probe(self):
        return True


class HealthyUSDA:
    def __init__(self):
        self.keys = []

    def probe(self, api_key):
        self.keys.append(api_key)
        return True


def test_environment_usda_key_overrides_user_config(tmp_path):
    path = tmp_path / "config.toml"
    stored = ProviderConfig(environ={}, config_path=path)
    stored.store_usda_key("stored-placeholder")

    credential = ProviderConfig(
        environ={"NOMNOM_USDA_KEY": "environment-placeholder"}, config_path=path
    ).usda_credential()

    assert credential is not None
    assert credential.source == "environment"
    assert credential.value == "environment-placeholder"


def test_stored_config_is_xdg_and_owner_only(tmp_path):
    config = ProviderConfig(environ={"XDG_CONFIG_HOME": str(tmp_path)})
    path = config.store_usda_key("stored-placeholder")

    assert path == tmp_path / "nomnomcli" / "config.toml"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert config.usda_credential().source == "user_config"


def test_invalid_config_is_actionable(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[providers.usda\napi_key = broken", encoding="utf-8")

    with pytest.raises(NomnomError) as caught:
        ProviderConfig(environ={}, config_path=path).usda_credential()

    assert caught.value.code == "provider_config_invalid"
    assert caught.value.details["path"] == str(path)


def test_interactive_setup_validates_before_secure_write(tmp_path):
    path = tmp_path / "config.toml"
    config = ProviderConfig(environ={}, config_path=path)
    usda = HealthyUSDA()

    result = setup_providers(
        interactive=True,
        config=config,
        off_client=HealthyOFF(),
        usda_client=usda,
        prompt=lambda _: "new-placeholder",
    )

    assert result["providers"]["usda"] == {
        "configured": True,
        "reachable": True,
        "key_source": "user_config",
    }
    assert usda.keys == ["new-placeholder"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_invalid_key_writes_nothing(tmp_path):
    path = tmp_path / "config.toml"

    class InvalidUSDA:
        def probe(self, api_key):
            raise NomnomError("usda_key_invalid", "invalid")

    with pytest.raises(NomnomError) as caught:
        setup_providers(
            interactive=True,
            config=ProviderConfig(environ={}, config_path=path),
            off_client=HealthyOFF(),
            usda_client=InvalidUSDA(),
            prompt=lambda _: "invalid-placeholder",
        )

    assert caught.value.code == "usda_key_invalid"
    assert not path.exists()


def test_noninteractive_setup_never_prompts(tmp_path):
    def unexpected_prompt(_):
        pytest.fail("noninteractive setup must not prompt")

    with pytest.raises(NomnomError) as caught:
        setup_providers(
            interactive=False,
            config=ProviderConfig(environ={}, config_path=tmp_path / "config.toml"),
            off_client=HealthyOFF(),
            usda_client=HealthyUSDA(),
            prompt=unexpected_prompt,
        )

    assert caught.value.code == "setup_requires_interactive"
    assert "nomnom doctor --json" in caught.value.details["action"]


def test_noninteractive_setup_uses_environment_key_without_prompt(tmp_path):
    def unexpected_prompt(_):
        pytest.fail("configured noninteractive setup must not prompt")

    usda = HealthyUSDA()
    result = setup_providers(
        interactive=False,
        config=ProviderConfig(
            environ={"NOMNOM_USDA_KEY": "environment-placeholder"},
            config_path=tmp_path / "config.toml",
        ),
        off_client=HealthyOFF(),
        usda_client=usda,
        prompt=unexpected_prompt,
    )

    assert result["providers"]["usda"]["key_source"] == "environment"
    assert usda.keys == ["environment-placeholder"]
    assert not (tmp_path / "config.toml").exists()


def test_doctor_report_is_deterministic_and_never_contains_key(tmp_path):
    path = tmp_path / "config.toml"
    config = ProviderConfig(environ={}, config_path=path)
    config.store_usda_key("never-print-placeholder")
    report = doctor_report(
        config=config, off_client=HealthyOFF(), usda_client=HealthyUSDA()
    )

    assert report == {
        "providers": {
            "openfoodfacts": {"configured": True, "reachable": True},
            "usda": {
                "configured": True,
                "reachable": True,
                "key_source": "user_config",
            },
        }
    }
    assert "never-print-placeholder" not in json.dumps(report)
