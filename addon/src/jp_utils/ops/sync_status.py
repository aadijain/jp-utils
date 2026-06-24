"""Status-sync operation: a word card's state -> a vocab-store status event.

The writer for the mining loop's last step (the known-set is "updated as cards are
encountered"). A single :class:`StatusOperation` on the WORD pipeline - it writes no
field; its only effect is an append to ``/v1/vocab/words``. The word deck is the
single source of truth for the seen->learnt progression:

- a NEW, un-suspended word card (just generated from a mined sentence, not yet
  studied) -> its word is ``seen``;
- a REVIEWED or SUSPENDED word card -> its word is ``learnt`` (suspending a card is a
  deliberate "I know this" just like reviewing it).

Each card's ``word`` field is deinflected to its lemma via ``POST /v1/text/normalize``;
the **reading** is taken from the card's own ``word-reading`` field when it has one
(the reading the card was enriched with), falling back to the deinflected reading.
Both the lemma and reading key the vocab event ``(lemma, reading)``. ``word-reading``
is an input but optional - only ``word`` is required, so a card not yet enriched with
a reading still syncs. It runs over the
deck's notes on the start-sweep (no reviewer hook - the "status axis" decision); events
are ``anki``-sourced and appended upgrade-only, so the sweep is idempotent and a
still-new card never downgrades a word already reviewed into ``learnt``.
"""

from ..client import BackendClient
from .base import StatusOperation
from .nplus1 import strip_markup

# The /v1/vocab/words contract is plain strings over the wire; the add-on stays
# stdlib-only (it never imports the vendored `shared` enums at runtime), so the
# status/source axes are the literal VocabAction/VocabSource values.
_SOURCE_ANKI = "anki"


class SyncWordStatusOperation(StatusOperation):
    key = "sync-word-status"
    label = "Sync word status to vocab store"
    # `word` -> the lemma (REQUIRED). `word-reading` -> the event reading, OPTIONAL:
    # read when present, else the deinflected reading is used (a card not yet enriched
    # with one). As an optional input it shows in the I/O signature but isn't
    # mapping-validated and doesn't gate applicability - the framework handles both.
    input_aliases = ("word",)
    optional_input_aliases = ("word-reading",)

    def collect(
        self,
        client: BackendClient,
        seen_sources: list[dict[str, str]],
        learnt_sources: list[dict[str, str]],
    ) -> list[dict]:
        # Seen then learnt, paired with the status each card state confers.
        sources = list(seen_sources) + list(learnt_sources)
        actions = ["seen"] * len(seen_sources) + ["learnt"] * len(learnt_sources)
        surfaces = [strip_markup(s.get("word", "")) for s in sources]
        if not surfaces:
            return []
        # One batched deinflect for the lemma (+ a fallback reading).
        resp = client.post("/v1/text/normalize", {"surfaces": surfaces})
        results = resp.get("results", [])
        entries = []
        for source, result, action in zip(sources, results, actions, strict=True):
            lemma = result.get("lemma", "")
            if not lemma:
                continue
            # Prefer the card's own reading; fall back to the deinflected one.
            reading = strip_markup(source.get("word-reading", "")).strip() or result.get(
                "reading", ""
            )
            entries.append(
                {
                    "lemma": lemma,
                    "reading": reading,
                    "action": action,
                    "source": _SOURCE_ANKI,
                }
            )
        return entries
