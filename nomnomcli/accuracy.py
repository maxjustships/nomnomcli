from __future__ import annotations

from dataclasses import dataclass

from nomnomcli.errors import NomnomError

ACCURACY_PROFILES = ("practical", "balanced", "exact")
DEFAULT_ACCURACY_PROFILE = "balanced"


@dataclass(frozen=True, slots=True)
class AccuracyProfile:
    name: str
    default_portion_policy: str
    branded_generic_fallback: str
    exact_brand_evidence: bool


PROFILE_SPECS = {
    "practical": AccuracyProfile(
        name="practical",
        default_portion_policy="estimate",
        branded_generic_fallback="search_first",
        exact_brand_evidence=False,
    ),
    "balanced": AccuracyProfile(
        name="balanced",
        default_portion_policy="estimate",
        branded_generic_fallback="material_risk_only",
        exact_brand_evidence=False,
    ),
    "exact": AccuracyProfile(
        name="exact",
        default_portion_policy="strict",
        branded_generic_fallback="never",
        exact_brand_evidence=True,
    ),
}


def validate_accuracy_profile(value: str, *, source: str, path: str | None = None) -> str:
    profile = value.strip()
    if profile not in ACCURACY_PROFILES:
        details = {"source": source, "allowed": list(ACCURACY_PROFILES)}
        if path is not None:
            details["path"] = path
        raise NomnomError(
            "accuracy_profile_invalid",
            f"Unsupported accuracy profile: {profile or '(empty)'}",
            details=details,
        )
    return profile


def profile_spec(name: str) -> AccuracyProfile:
    return PROFILE_SPECS[name]
