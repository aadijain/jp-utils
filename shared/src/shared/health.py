"""Health-check response contract."""

from dataclasses import dataclass, field


@dataclass
class DictStatus:
    name: str  # "meanings" | "frequency" | "furigana"
    loaded: bool
    entries: int


@dataclass
class HealthResponse:
    status: str  # "ok" when cache built, every dict loaded, and tokenizer ready; else "degraded"
    service: str
    version: str
    cache_built: bool
    tokenizer_ready: bool
    dicts: list[DictStatus] = field(default_factory=list)
