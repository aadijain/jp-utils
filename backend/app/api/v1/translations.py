"""Stateful translation-queue router (/v1/translations).

The async seam between the add-on and an external batch translator. The add-on
only ever calls `lookup` (which auto-enqueues unknown sentences); `export` and
`results` are the worker-facing CSV halves, shaped so a header-aware batch run
consumes the export directly and its output CSV posts straight back. The queue
is read from app.state (never constructed per request). Must not import the
text or vocab modules.
"""

from fastapi import APIRouter, Depends, Query, Request, Response

from app.errors import APIError
from app.translations import TranslationQueue
from shared.translations import (
    TranslationImportResponse,
    TranslationLookupRequest,
    TranslationLookupResponse,
)

router = APIRouter(prefix="/translations", tags=["translations"])


def get_translation_queue(request: Request) -> TranslationQueue:
    queue: TranslationQueue | None = getattr(request.app.state, "translation_queue", None)
    if queue is None:
        raise APIError(503, "translations_unavailable", "Translation queue is not available")
    return queue


@router.post("/lookup")
def lookup(
    req: TranslationLookupRequest,
    queue: TranslationQueue = Depends(get_translation_queue),
) -> TranslationLookupResponse:
    """Answer each query (aligned) and enqueue the sentences seen for the first time.

    One round trip covers the whole flow: a `done` result carries the finished
    translation + notes; anything else is (now) `pending` and will be picked up
    by the worker. Re-querying is idempotent - keys are content hashes of the
    normalized sentence.
    """
    return queue.lookup(req.queries)


@router.get("/export")
def export(
    status: str = Query("pending", pattern="^pending$"),
    queue: TranslationQueue = Depends(get_translation_queue),
) -> Response:
    """The pending queue as a worker-ready CSV (header ``key,source,context``)."""
    del status  # only the pending set is exportable; the param names the intent
    return Response(content=queue.export_pending(), media_type="text/csv")


@router.post("/results")
async def import_results(
    request: Request,
    queue: TranslationQueue = Depends(get_translation_queue),
) -> TranslationImportResponse:
    """Apply a worker output CSV (raw request body): mark translated rows done.

    Rows with a blank translation stay pending (the worker retries its own
    errors); unknown keys are skipped. Malformed CSV -> 400.
    """
    body = await request.body()
    try:
        return queue.import_results(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise APIError(400, "invalid_results_csv", str(exc)) from exc
