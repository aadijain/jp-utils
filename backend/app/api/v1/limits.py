"""Batch-size guard for the batch-first endpoints.

Every /v1 endpoint takes a whole batch in one request, and batch-first clients
legitimately send very large ones. So the cap is not a throttle - it exists so a
malformed or runaway caller can't make the service materialize an unbounded list,
tokenize forever, or hold a request body of arbitrary size in memory.

It is therefore set well above any realistic batch (see :data:`MAX_BATCH`) and
enforced here rather than on the contract: `shared/` stays plain dataclasses, with
pydantic kept as the backend-only validation layer (see `app/config.py`).
"""

from collections.abc import Sized

from app.errors import APIError

# Deck-sized batches are normal, so the cap sits far above any real batch: it
# never fires in ordinary use and only catches a caller that has lost the plot.
MAX_BATCH = 10_000


def check_batch(items: Sized, field: str, limit: int = MAX_BATCH) -> None:
    """Reject a batch larger than `limit` with a coded 413.

    `field` names the offending request field so the message points at it.
    """
    size = len(items)
    if size > limit:
        raise APIError(
            413,
            "batch_too_large",
            f"{field} has {size} entries; this endpoint accepts at most {limit} per request",
        )
