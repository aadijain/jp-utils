"""Standard error-response contract.

Every backend failure (auth, validation, not-found, unexpected) serializes to this
one shape so the add-on can parse a single error format. See the backend's
exception handlers for the mapping from exceptions to this model.
"""

from dataclasses import dataclass


@dataclass
class ErrorBody:
    code: str
    message: str


@dataclass
class ErrorResponse:
    error: ErrorBody
