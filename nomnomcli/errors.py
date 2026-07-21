import math


class NomnomError(Exception):
    """A user-correctable error with stable machine-readable details."""

    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict:
        error = {"code": self.code, "message": self.message}
        # A small set of resolution fields are part of the public error contract.
        # Keep `details` intact for backwards-compatible machine consumers.
        for key in ("candidate", "alternatives", "setup", "would_write"):
            if key in self.details:
                error[key] = self.details[key]
        if self.details:
            error["details"] = self.details
        return {"error": error}


class ProviderUnavailableError(NomnomError):
    """A provider failure whose retryability is explicit in the public contract."""

    def __init__(
        self,
        provider: str,
        code: str,
        message: str,
        *,
        retryable: bool,
        details: dict | None = None,
    ) -> None:
        super().__init__(
            code,
            message,
            details={"provider": provider, "retryable": retryable, **(details or {})},
        )
        self.provider = provider
        self.retryable = retryable


def require_finite_numbers(value: object) -> None:
    """Reject non-finite values before persistence or strict JSON output."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NomnomError(
                "non_finite_result",
                "Command result contains a non-finite numeric value",
                details={
                    "would_write": False,
                    "action": "Repair or remove non-finite persisted nutrition values and retry.",
                },
            )
        return
    if isinstance(value, dict):
        for item in value.values():
            require_finite_numbers(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            require_finite_numbers(item)
