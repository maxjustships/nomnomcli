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
        for key in ("candidate", "alternatives", "setup"):
            if key in self.details:
                error[key] = self.details[key]
        if self.details:
            error["details"] = self.details
        return {"error": error}
