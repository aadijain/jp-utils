"""Stateful vocabulary store router (/v1/vocab).

Personal vocabulary knowledge base, keyed on lemma+reading. The single
append-only store is read from app.state (never constructed per request). Must
not import the text module (the boundary that lets vocab extract later).
"""

from fastapi import APIRouter, Depends, Query, Request, Response

from app.errors import APIError
from app.vocab import VocabStore
from shared.vocab import (
    FilterByStatusRequest,
    FilterByStatusResponse,
    RecordRequest,
    RecordResponse,
    VocabStatus,
)

router = APIRouter(prefix="/vocab", tags=["vocab"])


def get_vocab_store(request: Request) -> VocabStore:
    store: VocabStore | None = getattr(request.app.state, "vocab_store", None)
    if store is None:
        raise APIError(503, "vocab_unavailable", "Vocabulary store is not available")
    return store


@router.post("/words")
def record_words(
    req: RecordRequest,
    store: VocabStore = Depends(get_vocab_store),
) -> RecordResponse:
    """Append a batch of vocab events.

    With `force` every entry applies as-is (a deliberate action); otherwise derived
    `seen`/`learnt` are upgrade-only and never downgrade or clobber a manual
    ignore/blacklist. `recorded` is the number of rows actually written.
    """
    recorded = store.record(req.entries, force=req.force)
    return RecordResponse(recorded=recorded, version=store.status().version)


@router.post("/filter-by-status")
def filter_by_status(
    req: FilterByStatusRequest,
    store: VocabStore = Depends(get_vocab_store),
) -> FilterByStatusResponse:
    """Return the subset of `req.words` whose status is in `req.statuses`.

    Defaults to unknown-only (the new-word hot path); generation passes
    {unknown, seen} with `match_lemma_only` so a reading mismatch can't surface a
    known word as unknown.
    """
    return store.filter_by_status(req.words, req.statuses, req.match_lemma_only)


@router.get("/status")
def status(store: VocabStore = Depends(get_vocab_store)) -> VocabStatus:
    """Recorded-word count, total events, and the current store version."""
    return store.status()


@router.get("/export")
def export(
    fmt: str = Query("json", alias="format", pattern="^(json|csv)$"),
    store: VocabStore = Depends(get_vocab_store),
) -> Response:
    """Export the current recorded set as JSON or CSV."""
    body = store.export(fmt)
    media_type = "text/csv" if fmt == "csv" else "application/json"
    return Response(content=body, media_type=media_type)
