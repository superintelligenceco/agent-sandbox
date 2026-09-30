"""Error types shared by the manager, backends, and API layer."""

from __future__ import annotations


class SandboxError(Exception):
    """Base class for errors that map to an HTTP response."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(SandboxError):
    status_code = 404
    code = "not_found"


class InvalidRequestError(SandboxError):
    status_code = 400
    code = "invalid_request"


class ForbiddenError(SandboxError):
    status_code = 403
    code = "forbidden"


class ConflictError(SandboxError):
    status_code = 409
    code = "conflict"


class LimitExceededError(SandboxError):
    status_code = 429
    code = "limit_exceeded"


class PayloadTooLargeError(SandboxError):
    status_code = 413
    code = "payload_too_large"


class BackendError(SandboxError):
    status_code = 502
    code = "backend_error"
