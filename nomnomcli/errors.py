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
        for key in (
            "candidate",
            "alternatives",
            "setup",
            "would_write",
            "original",
            "intent_version",
            "retrieval_query",
        ):
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
