"""Health-check response contract."""

from dataclasses import dataclass


@dataclass
class HealthResponse:
    status: str
    service: str
    version: str
