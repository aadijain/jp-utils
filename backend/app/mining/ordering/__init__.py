"""Interchangeable n+1 ordering algorithms, behind one registry.

Every orderer has the same pure signature - distinct content lemmas per sentence,
the known-lemma set, a lemma -> JPDB rank map - and returns a permutation of the
sentence indices, first = study first. They share the "learn as you place"
simulation that makes the order n+1 (placing a sentence marks its words known,
shrinking every other sentence's unknown set); they differ only in how they pick
the next sentence off that frontier:

- `greedy`  (`greedy.py`) - lexicographic tie-break tuple; the original.
- `fuzzy`   (`fuzzy.py`)  - one weighted cost blending the same signals.

:data:`ALGORITHMS` is the name -> orderer map the API dispatches on. Adding an
algorithm means adding a module and one entry here; nothing above this package
grows a branch. There is deliberately no default: callers name the algorithm.
"""

from collections.abc import Mapping
from typing import Protocol

from app.mining.ordering.greedy import greedy_order


class Orderer(Protocol):
    """The shape every ordering algorithm implements."""

    def __call__(
        self,
        sentences: list[list[str]],
        known: set[str],
        ranks: Mapping[str, int],
    ) -> list[int]: ...


ALGORITHMS: dict[str, Orderer] = {"greedy": greedy_order}

__all__ = ["ALGORITHMS", "Orderer", "greedy_order"]
