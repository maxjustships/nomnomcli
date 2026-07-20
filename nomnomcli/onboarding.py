from __future__ import annotations

import getpass
from collections.abc import Callable

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
    return {
        "providers": {
            "openfoodfacts": {"configured": True, "reachable": _reachable(off.probe)},
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
    off_reachable = _reachable(off.probe)
    credential = provider_config.usda_credential()
    if credential is not None:
        usda.probe(credential.value)
        return {
            "providers": {
                "openfoodfacts": {"configured": True, "reachable": off_reachable},
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
        "providers": {
            "openfoodfacts": {"configured": True, "reachable": off_reachable},
            "usda": {"configured": True, "reachable": True, "key_source": "user_config"},
        },
        "config_path": str(path),
    }
