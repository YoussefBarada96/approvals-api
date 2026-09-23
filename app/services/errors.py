"""Domain errors raised by the service layer.

Services don't know about HTTP. A single exception handler in app.main maps
these to status codes, so the same logic can be called from routes, the CLI
or the background worker.
"""


class DomainError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409


class InvalidInput(DomainError):
    status_code = 422
