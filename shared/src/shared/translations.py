"""Translation-queue request/response contract (the /v1/translations/* models).

Plain stdlib dataclasses, shared by the backend and the add-on. The queue is the
async seam between Anki and an external batch translator: the add-on looks up
sentences (which auto-enqueues unknown ones), an out-of-process worker drains the
pending set via CSV export/import, and later lookups return the finished
translations. Rows are keyed by a backend-computed content hash of the normalized
sentence - the add-on never sees the key; lookup results align to the request.

The export/import halves of the contract are plain CSV (not modeled here): the
export emits ``key,source,context`` with a header row, and the import accepts the
worker's output CSV, which appends ``translation,notes`` columns.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class TranslationStatus(StrEnum):
    """A queued sentence's state. There is no failed state: the worker owns
    retries, and a row without a result simply stays pending."""

    PENDING = "pending"  # enqueued, no translation yet
    DONE = "done"  # translated; kept forever as a cache


@dataclass
class TranslationQuery:
    """One sentence to look up (and enqueue when unknown), batch-first.

    ``sentence`` is plain text with HTML/furigana ruby already stripped by the
    add-on. ``context`` is an optional native-subtitle line passed to the
    translator as reference; it never affects the row's key.
    """

    sentence: str = ""
    context: str = ""


@dataclass
class TranslationLookupRequest:
    queries: list[TranslationQuery]  # batch-first: one entry per note


@dataclass
class TranslationResult:
    """The queue's answer for one query (aligned to the request).

    ``translation``/``notes`` are filled only when ``status`` is ``done``.
    """

    status: TranslationStatus = TranslationStatus.PENDING
    translation: str = ""
    notes: str = ""


@dataclass
class TranslationLookupResponse:
    results: list[TranslationResult] = field(default_factory=list)  # aligned with queries


@dataclass
class TranslationImportResponse:
    """Outcome of a results-CSV import.

    ``done`` rows received a translation; ``skipped`` rows were left pending
    (blank translation - the worker retries those itself) or matched no queued key.
    """

    done: int = 0
    skipped: int = 0
