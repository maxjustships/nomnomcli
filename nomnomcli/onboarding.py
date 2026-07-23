from __future__ import annotations

import getpass
from collections.abc import Callable

from nomnomcli.accuracy import profile_spec
from nomnomcli.config import ProviderConfig
from nomnomcli.errors import NomnomError
from nomnomcli.foods import USDA_SETUP_URL
from nomnomcli.off import OpenFoodFactsClient
from nomnomcli.usda import USDAClient


def _reachable(probe: Callable[[], bool]) -> bool:
    try:
        return bool(probe())
    except NomnomError:
        return False


def _off_status(off: OpenFoodFactsClient) -> dict:
    return {
        "configured": True,
        "product_lookup_reachable": _reachable(off.probe_product),
        "full_text_search_ready": _reachable(off.probe),
    }


def doctor_report(
    *,
    config: ProviderConfig | None = None,
    off_client: OpenFoodFactsClient | None = None,
    usda_client: USDAClient | None = None,
) -> dict:
    provider_config = config or ProviderConfig()
    off = off_client or OpenFoodFactsClient()
    usda = usda_client or USDAClient()
    try:
        credential = provider_config.usda_credential()
    except NomnomError:
        credential = None
    profile = provider_config.accuracy_profile()
    spec = profile_spec(profile)
    return {
        "accuracy": {
            "profile": profile,
            "portion_policy": provider_config.portion_policy(),
            "branded_generic_fallback": spec.branded_generic_fallback,
        },
        "providers": {
            "openfoodfacts": _off_status(off),
            "usda": {
                "configured": credential is not None,
                "reachable": (
                    _reachable(lambda: usda.probe(credential.value))
                    if credential is not None
                    else False
                ),
                "key_source": credential.source if credential is not None else None,
            },
        }
    }


def setup_status_report(
    *,
    config: ProviderConfig | None = None,
    off_client: OpenFoodFactsClient | None = None,
    usda_client: USDAClient | None = None,
) -> dict:
    """Return prompt-free provider setup state without credential material."""
    report = doctor_report(
        config=config,
        off_client=off_client,
        usda_client=usda_client,
    )
    usda = report["providers"]["usda"]
    usda.update(
        {
            "purpose": "no-label generic-food lookup",
            "signup_url": USDA_SETUP_URL,
        }
    )
    if usda["configured"] and usda["reachable"]:
        report["status"] = "connected"
        report["generic_coverage"] = "enhanced"
        usda["next_action"] = None
    elif usda["configured"]:
        report["status"] = "base_ready"
        report["generic_coverage"] = "base"
        usda["next_action"] = {
            "command": "nomnom setup",
            "optional": True,
            "message": (
                "Optional: reconnect USDA to restore broader no-photo raw/generic food coverage."
            ),
        }
    else:
        report["status"] = "base_ready"
        report["generic_coverage"] = "base"
        usda["next_action"] = {
            "command": "nomnom setup",
            "optional": True,
            "message": (
                "Optional: connect USDA for broader no-photo raw/generic food coverage."
            ),
        }
    return {"status": report.pop("status"), **report}


def setup_providers(
    *,
    interactive: bool,
    config: ProviderConfig | None = None,
    off_client: OpenFoodFactsClient | None = None,
    usda_client: USDAClient | None = None,
    prompt: Callable[[str], str] | None = None,
) -> dict:
    provider_config = config or ProviderConfig()
    off = off_client or OpenFoodFactsClient()
    usda = usda_client or USDAClient()
    off_status = _off_status(off)
    credential = provider_config.usda_credential()
    if credential is not None:
        usda.probe(credential.value)
        return {
            "accuracy_profile": provider_config.accuracy_profile(),
            "providers": {
                "openfoodfacts": off_status,
                "usda": {
                    "configured": True,
                    "reachable": True,
                    "key_source": credential.source,
                },
            }
        }
    if not interactive:
        raise NomnomError(
            "setup_requires_interactive",
            "USDA is not configured and setup cannot prompt on non-interactive stdin",
            details={
                "signup_url": USDA_SETUP_URL,
                "action": (
                    "Run nomnom setup in an interactive terminal, or set NOMNOM_USDA_KEY "
                    "and run nomnom doctor --json"
                ),
            },
        )
    api_key = (prompt or getpass.getpass)("USDA API key (input hidden): ").strip()
    if not api_key:
        raise NomnomError(
            "usda_key_invalid",
            "USDA API key must not be empty; configuration was not changed",
            details={"signup_url": USDA_SETUP_URL},
        )
    usda.probe(api_key)
    path = provider_config.store_usda_key(api_key)
    return {
        "accuracy_profile": provider_config.accuracy_profile(),
        "providers": {
            "openfoodfacts": off_status,
            "usda": {"configured": True, "reachable": True, "key_source": "user_config"},
        },
        "config_path": str(path),
    }
