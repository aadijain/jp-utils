"""Mining-loop composition layer.

The only place the stateless text service and the stateful vocab store are wired
together. The text and vocab modules
still must not import each other - this package sits above both. The ordering
algorithms (`ordering/`, keyed by name in :data:`ALGORITHMS`) are *pure* functions
over already-extracted lemma sets, tested in isolation; :func:`nplus1_sort`
(`sort.py`) is the impure tail that resolves content words from the tokenizer +
known set from the store and feeds the chosen one, so the API router stays thin
marshalling.
"""

from app.mining.ordering import ALGORITHMS, greedy_order
from app.mining.sort import nplus1_sort

__all__ = ["ALGORITHMS", "greedy_order", "nplus1_sort"]
