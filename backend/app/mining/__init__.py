"""Mining-loop composition layer.

The only place the stateless text service and the stateful vocab store are wired
together (n+1 sort now; vocab-card generation later). The text and vocab modules
still must not import each other - this package sits above both. The greedy core
(:func:`nplus1_order`, `ordering.py`) is a *pure* function over already-extracted
lemma sets, tested in isolation; :func:`nplus1_sort` (`sort.py`) is the impure tail
that resolves content words from the tokenizer + known set from the store and feeds
the greedy, so the API router stays thin marshalling.
"""

from app.mining.ordering import nplus1_order
from app.mining.sort import nplus1_sort

__all__ = ["nplus1_order", "nplus1_sort"]
