"""Pure sequencing helper, as consumed by the new-card reposition path (ui/run.py).

The order-realizing behaviour is exercised in depth in ``test_ops_nplus1.py`` (the
``rank`` field writer). These lock the module's own home and the property the
reposition path relies on: feeding current ``due`` values yields a change only for the
cards that actually move.
"""

from jp_utils.sequencing import stable_sequence


def _movers(order: list[int], current: list[int | None]) -> set[int]:
    """Item indices whose assigned value differs from their current value."""
    assigned = stable_sequence(order, current)
    assert set(assigned) == set(order)  # every item gets a value
    # Ordering by the assigned values reproduces the requested order.
    assert sorted(order, key=assigned.__getitem__) == order
    return {i for i, v in assigned.items() if current[i] != v}


def test_already_ordered_due_moves_nothing():
    # Cards whose current `due` already matches the target order keep every `due`.
    assert _movers([0, 1, 2, 3], [10, 20, 30, 40]) == set()


def test_one_out_of_place_card_moves_only_that_card():
    # Card 3 belongs at the front; 0,1,2 stay put (longest increasing run).
    assert _movers([3, 0, 1, 2], [10, 20, 30, 40]) == {3}


def test_gap_exhaustion_renumbers_all():
    # Cards 0 and 1 anchor at the tight pair 100/101; cards 2 and 3 must sort between
    # them but there's no integer room, so the fallback renumbers every card.
    assert _movers([0, 2, 3, 1], [100, 101, 500, 400]) == {0, 1, 2, 3}
