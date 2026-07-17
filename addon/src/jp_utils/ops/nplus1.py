"""n+1 sequence operation: ``sentence`` -> a per-card ``sequence`` number.

Orders the new-card queue so each successive card introduces as few unknown words
as possible (i+1 sentence sequencing). The whole batch of sentences is sent to
``POST /v1/mining/nplus1sort``; the backend tokenizes them, scores each against the
learnt set, and returns a greedy ordering as a 0-based sequence number per card.
This op only *writes* that number into the ``rank`` field (the shared sort key the
int-sort op also orders by) - actually repositioning the cards by it is a separate
sort op.

Unlike the other field ops this is a **global** computation (every card's number
depends on the whole batch), so it always recomputes (no ``only_if_empty``) and is
idempotent only by recompute-vs-compare. HTML/ruby is stripped before sending so
markup never reaches the tokenizer (the backend never sees it).
"""

import html
import re

from ..client import BackendClient
from ..sequencing import stable_sequence
from .base import FieldOperation

# Drop ruby readings entirely (``<rt>``/``<rp>`` content), then any remaining tags;
# unescape what's left. Tokenizing the base text only - readings would be noise.
_RUBY_READING_RE = re.compile(r"<r[tp]\b[^>]*>.*?</r[tp]>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def strip_markup(text: str) -> str:
    """Plain text of a sentence field: ruby readings and all HTML tags removed."""
    text = _RUBY_READING_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    return html.unescape(text)


def _parse_int(raw: str) -> int | None:
    try:
        return int((raw or "").strip())
    except ValueError:
        return None


class Nplus1SequenceOperation(FieldOperation):
    key = "nplus1-sequence"
    label = "Assign n+1 sequence"
    description = (
        "Computes an n+1 study order for the deck's sentences (each sentence "
        "introduces about one unknown word) and writes each card's position to "
        "the rank field. Uses the vocab store to know which words you already "
        "know."
    )
    input_aliases = ("sentence",)
    output_alias = "rank"
    params_spec = ()  # no only_if_empty: the order is global and must always recompute

    def compute(
        self, client: BackendClient, sources: list[dict[str, str]], params: dict | None = None
    ) -> list[str | None]:
        n = len(sources)
        sentences = [{"text": strip_markup(s.get("sentence", ""))} for s in sources]
        resp = client.post("/v1/mining/nplus1sort", {"sentences": sentences})
        results = resp.get("results", [])

        # Backend study-order rank (0-based) per card; cards without one are left
        # out of the ordering (and unchanged). Distinct from the `rank` FIELD below
        # (where the assigned number is written).
        order_rank = {
            i: r["sequence"] for i, r in enumerate(results[:n]) if r.get("sequence") is not None
        }
        if not order_rank:
            return [None] * n
        order = sorted(order_rank, key=order_rank.__getitem__)
        current = [_parse_int(s.get("rank", "")) for s in sources]

        assigned = stable_sequence(order, current)
        out: list[str | None] = [None] * n
        for index, value in assigned.items():
            out[index] = str(value)
        return out
