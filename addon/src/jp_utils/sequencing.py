"""Minimal-churn integer sequencing over a desired order.

Given a target order (as item indices) and each item's current integer value,
assign new values that realize the order while **reusing** the values of items
already sitting in ascending order (a longest increasing subsequence), so only the
items that actually move get a new value. Movers are slotted into the gaps between
the kept "anchors" (:data:`_STEP`-spaced), with a full evenly-spaced renumber as the
fallback when a gap can't fit its movers.

Pure and ``aqt``-free, so it is unit-testable and shared by two callers that face the
same problem:

* :mod:`jp_utils.ops.nplus1` - minimizing writes to the ``rank`` FIELD.
* :mod:`jp_utils.ui.run` - minimizing ``due`` rewrites when repositioning new cards.
"""

import bisect

# Gap between freshly-assigned values, leaving room to slot a moved item between two
# neighbours without renumbering them (see `stable_sequence`).
_STEP = 1000


def _lis_positions(values: list[int | None]) -> set[int]:
    """Positions of a longest strictly-increasing subsequence over the non-None values.

    These are the items already sitting in correct ascending order: keeping their
    values is what minimizes writes (everything else is renumbered into the gaps).
    """
    tails: list[int] = []  # tails[k] = position ending the best length-(k+1) subseq
    tail_values: list[int] = []
    prev = [-1] * len(values)
    for i, value in enumerate(values):
        if value is None:
            continue
        k = bisect.bisect_left(tail_values, value)  # strictly increasing
        prev[i] = tails[k - 1] if k > 0 else -1
        if k == len(tails):
            tails.append(i)
            tail_values.append(value)
        else:
            tails[k] = i
            tail_values[k] = value
    chosen: set[int] = set()
    i = tails[-1] if tails else -1
    while i != -1:
        chosen.add(i)
        i = prev[i]
    return chosen


def _fill_gap(lo: int | None, hi: int | None, count: int) -> list[int] | None:
    """`count` strictly-increasing ints in the open interval (lo, hi); None if no room.

    ``lo``/``hi`` None mean the run sits before the first / after the last anchor.
    """
    if count == 0:
        return []
    if lo is None and hi is None:
        return [(k + 1) * _STEP for k in range(count)]
    if lo is None:
        assert hi is not None  # the both-None case returned above
        return [hi - (count - k) * _STEP for k in range(count)]
    if hi is None:
        return [lo + (k + 1) * _STEP for k in range(count)]
    if hi - lo - 1 < count:  # not enough integers between the anchors
        return None
    inc = (hi - lo) // (count + 1)
    return [lo + inc * (k + 1) for k in range(count)]


def stable_sequence(order: list[int], current: list[int | None]) -> dict[int, int]:
    """Assign ascending values realizing `order`, reusing existing values.

    ``order`` is the desired order as item indices; ``current[i]`` is item i's
    existing value (None if unset/garbage). Items already in correct ascending order
    (a longest increasing subsequence) keep their value; the rest are renumbered into
    the gaps. Returns ``{item_index: new_value}`` for every item in ``order``. If a gap
    can't fit its items, falls back to a full evenly-spaced renumber.
    """
    n = len(order)
    values_in_order = [current[idx] for idx in order]
    anchors = _lis_positions(values_in_order)

    result: dict[int, int] = {}
    prev_value: int | None = None
    i = 0
    while i < n:
        if i in anchors:
            anchor_value = values_in_order[i]
            assert anchor_value is not None  # anchors are LIS positions over non-None values
            result[order[i]] = anchor_value
            prev_value = anchor_value
            i += 1
            continue
        j = i
        while j < n and j not in anchors:
            j += 1
        next_value = values_in_order[j] if j < n else None
        filled = _fill_gap(prev_value, next_value, j - i)
        if filled is None:  # gap exhausted: give up on stability, renumber cleanly
            return {order[k]: (k + 1) * _STEP for k in range(n)}
        for position, value in zip(range(i, j), filled, strict=True):
            result[order[position]] = value
        prev_value = filled[-1]
        i = j
    return result
