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
deck's notes on the start-sweep (no reviewer hook - the "status axis" decision); the
card-state events are ``anki``-sourced and appended upgrade-only, so the sweep is
idempotent and a still-new card never downgrades a word already reviewed into
``learnt``.

**Custom tags.** A card carrying one of the fixed :data:`TAG_ACTIONS` tags
forces its word to the mapped action (``learnt`` / ``ignored`` / ``blacklisted``),
overriding whatever its card state would confer - tags take priority. ``ignored`` and
``blacklisted`` are terminal states unreachable from card state; a ``learnt`` tag
force-marks a word known even while its card is still new. Tag events are posted
**forced** (a deliberate action, bypassing the upgrade-only guard), so unlike the
card-state events they re-append on every sweep - benign in the append-only store.
The wiring excludes tagged cards from the seen/learnt buckets, so a card is either
tag-driven or state-driven, never both.
"""

from ..client import BackendClient
from .base import StatusOperation
from .nplus1 import strip_markup

# The /v1/vocab/words contract is plain strings over the wire; the add-on stays
# stdlib-only (it never imports the vendored `shared` enums at runtime), so the
# status/source axes are the literal VocabAction/VocabSource values.
_SOURCE_ANKI = "anki"

# Fixed Anki tag -> forced vocab action. Hierarchical `jp::*` tags keep them
# grouped in Anki's tag sidebar and search cleanly (`tag:jp::learnt`). A card with
# one of these overrides its card-state classification.
TAG_ACTIONS = {
    "jp::learnt": "learnt",
    "jp::ignored": "ignored",
    "jp::blacklisted": "blacklisted",
}


class SyncWordStatusOperation(StatusOperation):
    key = "sync-word-status"
    label = "Sync word status to vocab store"
    description = (
        "Reports each word card's study state to the backend vocab store, which "
        "sequencing and generation ops use to know which words you know. A new, "
        "not-yet-studied card marks its word as seen; a reviewed or suspended "
        "card marks it as learnt. Cards tagged jp::learnt, jp::ignored, or "
        "jp::blacklisted force that status instead, overriding card state."
    )
    # `word` -> the lemma (REQUIRED). `word-reading` -> the event reading, OPTIONAL:
    # read when present, else the deinflected reading is used (a card not yet enriched
    # with one). As an optional input it shows in the I/O signature but isn't
    # mapping-validated and doesn't gate applicability - the framework handles both.
    input_aliases = ("word",)
    optional_input_aliases = ("word-reading",)
    tag_actions = TAG_ACTIONS

    def collect(
        self,
        client: BackendClient,
        seen_sources: list[dict[str, str]],
        learnt_sources: list[dict[str, str]],
        tagged_sources: dict[str, list[dict[str, str]]],
    ) -> tuple[list[dict], list[dict]]:
        # Each source paired with (action, force): card state is upgrade-only, tags
        # are forced (they take priority). One `force` flag per source lets the single
        # deinflect below cover every bucket, then splits the events back out.
        triples: list[tuple[dict[str, str], str, bool]] = []
        triples += [(s, "seen", False) for s in seen_sources]
        triples += [(s, "learnt", False) for s in learnt_sources]
        for action, sources in tagged_sources.items():
            triples += [(s, action, True) for s in sources]
        if not triples:
            return [], []
        # One batched deinflect for every source's lemma (+ a fallback reading).
        surfaces = [strip_markup(s.get("word", "")) for s, _, _ in triples]
        resp = client.post("/v1/text/normalize", {"surfaces": surfaces})
        results = resp.get("results", [])
        unforced: list[dict] = []
        forced: list[dict] = []
        for (source, action, force), result in zip(triples, results, strict=True):
            lemma = result.get("lemma", "")
            if not lemma:
                continue
            # Prefer the card's own reading; fall back to the deinflected one.
            reading = strip_markup(source.get("word-reading", "")).strip() or result.get(
                "reading", ""
            )
            entry = {
                "lemma": lemma,
                "reading": reading,
                "action": action,
                "source": _SOURCE_ANKI,
            }
            (forced if force else unforced).append(entry)
        return unforced, forced
