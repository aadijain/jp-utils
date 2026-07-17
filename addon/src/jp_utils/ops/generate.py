"""Generate-vocab operation: a mined sentence -> new vocab cards.

Attaches to the SENTENCE pipeline. For each reviewed source sentence it extracts
the content words (``POST /v1/text/content-words``) and keeps only those still new
to the user (``POST /v1/vocab/filter-by-status`` with ``{unknown, seen}``, matched
**lemma-only** so a dict-vs-Sudachi reading mismatch can't resurrect a known word).
Those survivors are what the wiring layer turns into Lapis word notes - this op is
just the backend composition (it creates no notes itself; deduping against existing
notes and copying context fields needs ``mw.col`` and happens on the UI thread).

Targets (the word deck + its note type) and the on-existing policy are params, so
the whole thing reuses the pipeline machinery (config, params dialog, validation,
"Run now", auto-run-on-start) with no separate feature wiring.
"""

from ..client import BackendClient
from ..config import ALIASES
from .base import GenerateOperation, ParamSpec
from .nplus1 import strip_markup

# Every alias is offerable in the copy whitelist; an entry only copies when actually
# mapped on both note types and not a seed (see :func:`jp_utils.generation.context_aliases`).
# Default-checked: the sentence-context fields (the ``sentence*`` aliases), which is what
# usually carries onto a word card.
CONTEXT_ALIAS_CHOICES = ALIASES
DEFAULT_CONTEXT_ALIASES = tuple(a for a in ALIASES if a.startswith("sentence"))

TARGET_DECK = ParamSpec(
    "target_deck",
    "Target word deck",
    "choice",
    default="",
    choices_source="decks",
    description="The deck new vocab cards are created in.",
)
TARGET_NOTE_TYPE = ParamSpec(
    "target_note_type",
    "Target note type",
    "choice",
    default="",
    choices_source="note_types",
    description="The note type of generated vocab cards (e.g. Lapis).",
)
ON_EXISTING = ParamSpec(
    "on_existing",
    "When a card already exists",
    "choice",
    default="skip",
    choices=("skip", "overwrite", "duplicate"),
    description="A card with the same word + reading already exists: skip leaves it, "
    "overwrite refreshes its seeded + copied fields, duplicate creates another card anyway.",
)
COPY_ALIASES = ParamSpec(
    "copy_aliases",
    "Copy context fields",
    "multichoice",
    default=DEFAULT_CONTEXT_ALIASES,
    choices=CONTEXT_ALIAS_CHOICES,
    description="Sentence-context aliases to copy onto the new card (each only copies when "
    "mapped on both note types). Unchecked means copy nothing; word and word-reading are "
    "always seeded regardless.",
)


class GenerateVocabOperation(GenerateOperation):
    key = "generate-vocab"
    label = "Generate vocab cards"
    description = (
        "Creates new vocab cards in a target deck from the content words of a "
        "mined sentence, skipping words the vocab store already knows. Configure "
        "the target deck and note type in the options."
    )
    input_aliases = ("sentence",)  # the field tokenized for content words
    params_spec = (TARGET_DECK, TARGET_NOTE_TYPE, ON_EXISTING, COPY_ALIASES)

    def generate(self, client: BackendClient, sources: list[dict[str, str]]) -> list[list[dict]]:
        texts = [strip_markup(s.get("sentence", "")) for s in sources]
        resp = client.post("/v1/text/content-words", {"texts": texts})
        results = resp.get("results", [])
        # Align to sources; each entry is a list of {"lemma", "reading"} dicts.
        word_lists = [results[i] if i < len(results) else [] for i in range(len(sources))]

        candidates = [w for word_list in word_lists for w in word_list]
        if not candidates:
            return [[] for _ in sources]

        # One batched status filter over every candidate; keep new words only.
        filtered = client.post(
            "/v1/vocab/filter-by-status",
            {"words": candidates, "statuses": ["unknown", "seen"], "match_lemma_only": True},
        )
        kept_lemmas = {w["lemma"] for w in filtered.get("matched", [])}
        return [[w for w in word_list if w["lemma"] in kept_lemmas] for word_list in word_lists]
