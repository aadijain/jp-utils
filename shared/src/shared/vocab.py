"""Vocab-store request/response contract (the /v1/vocab/* models).

Plain stdlib dataclasses (+ StrEnums), shared by the backend and the add-on. The
store is keyed on lemma+reading (never Anki card ids) and is append-only: each
write is an event, and a word's current status is the latest event per
(lemma, reading).
"""

from dataclasses import dataclass, field
from enum import StrEnum


class VocabAction(StrEnum):
    """What an event records about a (lemma, reading) on the status axis.

    A word progresses: absence of any event -> ``unknown``; ``seen`` (it appeared
    in a reviewed sentence) -> ``learnt`` (its own word card was reviewed).
    ``ignored`` and ``blacklisted`` are manual terminal states off to the side;
    ``removed`` reverts a word back to ``unknown``.
    """

    SEEN = "seen"  # in a reviewed sentence -> known, but no word card yet
    LEARNT = "learnt"  # a word card was reviewed / seeded as known
    IGNORED = "ignored"  # particles/names: kept out of n+1 and generation
    BLACKLISTED = "blacklisted"  # explicitly never make a card; also not-new
    REMOVED = "removed"  # revert: the word becomes unknown again


class VocabSource(StrEnum):
    """Provenance of an event - pure (who/what wrote it, not what it means)."""

    MANUAL = "manual"  # a deliberate user entry
    ANKI = "anki"  # derived from Anki cards by the start-sweep


class WordStatus(StrEnum):
    """A word's current status - the projection of its latest event.

    ``unknown`` is the absence of any positive event (no rows, or latest
    ``removed``); the rest mirror the matching :class:`VocabAction`.
    """

    UNKNOWN = "unknown"
    SEEN = "seen"
    LEARNT = "learnt"
    IGNORED = "ignored"
    BLACKLISTED = "blacklisted"


@dataclass
class VocabWord:
    lemma: str  # dictionary form (canonical key together with `reading`)
    reading: str = ""  # hiragana; "" if none


@dataclass
class RecordEntry:
    lemma: str
    reading: str = ""
    action: VocabAction = VocabAction.LEARNT
    source: VocabSource = VocabSource.MANUAL


@dataclass
class RecordRequest:
    entries: list[RecordEntry]  # batch-first: append many events in one request
    # apply every entry as-is (a deliberate action); else derived events are
    # upgrade-only and won't downgrade or clobber a manual ignore/blacklist.
    force: bool = False


@dataclass
class RecordResponse:
    recorded: int  # rows actually appended (fewer than submitted when guarded)
    version: int  # store version after the write (monotonic; bumps per append)


@dataclass
class FilterByStatusRequest:
    words: list[VocabWord]  # batch-first: candidate words to test against the store
    # keep only words whose current status is in this set; default = unknown-only
    # (today's "new words"). Generation passes {unknown, seen}.
    statuses: list[WordStatus] = field(default_factory=lambda: [WordStatus.UNKNOWN])


@dataclass
class FilterByStatusResponse:
    # the subset of the request whose status is in the requested set
    matched: list[VocabWord] = field(default_factory=list)


@dataclass
class VocabStatus:
    count: int  # distinct recorded (not-unknown) words
    events: int  # total event rows
    version: int  # current store version (max event id)
