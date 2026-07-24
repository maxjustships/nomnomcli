from __future__ import annotations

import json
import stat

import pytest

from nomnomcli.config import ProviderConfig
from nomnomcli.errors import NomnomError
from nomnomcli.off import OFF_PRODUCT_PROBE_URL, OFF_SEARCH_URL, OpenFoodFactsClient
from nomnomcli.onboarding import doctor_report, setup_providers, setup_status_report
from nomnomcli.providers import RetryPolicy


class HealthyOFF:
    def probe_product(self):
        return True

    def probe(self):
        return True


class HealthyUSDA:
    def __init__(self):
        self.keys = []

    def probe(self, api_key):
        self.keys.append(api_key)
        return True


def test_generic_proxy_policy_defaults_to_allow_for_unbranded(tmp_path):
    config = ProviderConfig(environ={}, config_path=tmp_path / "missing.toml")

    assert config.generic_proxy_policy() == "allow_for_unbranded"


def test_generic_proxy_policy_environment_overrides_user_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[resolution]\ngeneric_proxy_policy = "ask"\n', encoding="utf-8"
    )
    config = ProviderConfig(
        environ={"NOMNOM_GENERIC_PROXY_POLICY": "exact_only"}, config_path=path
    )

    assert config.generic_proxy_policy() == "exact_only"


@pytest.mark.parametrize("policy", ["allow_for_unbranded", "ask", "exact_only"])
def test_generic_proxy_policy_accepts_every_documented_config_value(tmp_path, policy):
    path = tmp_path / "config.toml"
    path.write_text(
        f'[resolution]\ngeneric_proxy_policy = "{policy}"\n', encoding="utf-8"
    )

    assert ProviderConfig(environ={}, config_path=path).generic_proxy_policy() == policy


def test_invalid_generic_proxy_policy_is_structured(tmp_path):
    config = ProviderConfig(
        environ={"NOMNOM_GENERIC_PROXY_POLICY": "sometimes"},
        config_path=tmp_path / "config.toml",
    )

    with pytest.raises(NomnomError) as caught:
        config.generic_proxy_policy()

    assert caught.value.code == "generic_proxy_policy_invalid"
    assert caught.value.details["allowed"] == [
        "allow_for_unbranded",
        "ask",
        "exact_only",
    ]


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


def test_storing_usda_key_preserves_generic_proxy_policy(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[resolution]\ngeneric_proxy_policy = "exact_only"\n', encoding="utf-8"
    )
    config = ProviderConfig(environ={}, config_path=path)

    config.store_usda_key("stored-placeholder")

    assert config.usda_credential().value == "stored-placeholder"
    assert config.generic_proxy_policy() == "exact_only"


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
    assert result["providers"]["openfoodfacts"] == {
        "configured": True,
        "product_lookup_reachable": True,
        "full_text_search_ready": True,
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
        "accuracy": {
            "profile": "balanced",
            "portion_policy": "strict",
            "branded_generic_fallback": "material_risk_only",
        },
        "providers": {
            "openfoodfacts": {
                "configured": True,
                "product_lookup_reachable": True,
                "full_text_search_ready": True,
            },
            "usda": {
                "configured": True,
                "reachable": True,
                "key_source": "user_config",
            },
        }
    }
    assert "never-print-placeholder" not in json.dumps(report)


def test_doctor_distinguishes_off_product_reachability_from_full_text_readiness(
    tmp_path,
):
    class ProductOnlyOFF:
        def probe_product(self):
            return True

        def probe(self):
            raise NomnomError(
                "openfoodfacts_unavailable",
                "Open Food Facts full-text search is unavailable",
            )

    report = doctor_report(
        config=ProviderConfig(environ={}, config_path=tmp_path / "config.toml"),
        off_client=ProductOnlyOFF(),
        usda_client=HealthyUSDA(),
    )

    assert report["providers"]["openfoodfacts"] == {
        "configured": True,
        "product_lookup_reachable": True,
        "full_text_search_ready": False,
    }


def test_doctor_claims_follow_actual_mocked_off_capability_calls(tmp_path):
    calls = []

    class Response:
        headers = {}

        def __init__(self, payload, status_code=200):
            self.payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise NomnomError("http_error", "mocked HTTP failure")

        def json(self):
            return self.payload

    def get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        if url == OFF_PRODUCT_PROBE_URL:
            return Response({"status": 0})
        assert url == OFF_SEARCH_URL
        return Response({}, status_code=503)

    report = doctor_report(
        config=ProviderConfig(environ={}, config_path=tmp_path / "missing.toml"),
        off_client=OpenFoodFactsClient(
            request_get=get,
            retry_policy=RetryPolicy(max_attempts=1),
            sleep=lambda _: None,
        ),
        usda_client=HealthyUSDA(),
    )

    assert report["providers"]["openfoodfacts"] == {
        "configured": True,
        "product_lookup_reachable": True,
        "full_text_search_ready": False,
    }
    assert [url for url, _ in calls] == [OFF_PRODUCT_PROBE_URL, OFF_SEARCH_URL]
    assert "search_terms" not in calls[0][1]
    assert calls[1][1]["search_terms"] == "nomnom"


def test_setup_status_is_actionable_and_never_contains_key(tmp_path):
    path = tmp_path / "config.toml"
    config = ProviderConfig(environ={}, config_path=path)
    config.store_usda_key("never-emit-this-placeholder")

    report = setup_status_report(
        config=config, off_client=HealthyOFF(), usda_client=HealthyUSDA()
    )

    assert report["status"] == "connected"
    assert report["generic_coverage"] == "enhanced"
    assert report["providers"]["usda"] == {
        "configured": True,
        "reachable": True,
        "key_source": "user_config",
        "purpose": "no-label generic-food lookup",
        "signup_url": "https://fdc.nal.usda.gov/api-key-signup.html",
        "next_action": None,
    }
    assert "never-emit-this-placeholder" not in json.dumps(report)


def test_setup_status_unconfigured_is_base_ready_with_optional_enhancement(tmp_path):
    report = setup_status_report(
        config=ProviderConfig(environ={}, config_path=tmp_path / "missing.toml"),
        off_client=HealthyOFF(),
        usda_client=HealthyUSDA(),
    )

    assert report["status"] == "base_ready"
    assert report["generic_coverage"] == "base"
    assert report["providers"]["usda"]["configured"] is False
    assert report["providers"]["usda"]["reachable"] is False
    assert report["providers"]["usda"]["next_action"] == {
        "command": "nomnom setup",
        "optional": True,
        "message": (
            "Optional: connect USDA for broader no-photo raw/generic food coverage."
        ),
    }


def test_setup_status_unreachable_usda_preserves_base_ready_coverage(tmp_path):
    class UnreachableUSDA:
        def probe(self, api_key):
            raise NomnomError("usda_unavailable", "USDA is unavailable")

    path = tmp_path / "config.toml"
    config = ProviderConfig(environ={}, config_path=path)
    config.store_usda_key("unreachable-placeholder")

    report = setup_status_report(
        config=config, off_client=HealthyOFF(), usda_client=UnreachableUSDA()
    )

    assert report["status"] == "base_ready"
    assert report["generic_coverage"] == "base"
    assert report["providers"]["usda"]["next_action"] == {
        "command": "nomnom setup",
        "optional": True,
        "message": (
            "Optional: reconnect USDA to restore broader no-photo raw/generic food coverage."
        ),
    }
