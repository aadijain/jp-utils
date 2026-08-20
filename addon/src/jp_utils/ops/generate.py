"""Generate-vocab operation: a mined sentence -> new vocab cards.

Attaches to the SENTENCE pipeline. For each reviewed source sentence it extracts
the content words (``POST /v1/text/content-words``) and keeps only those still new
to the user (``POST /v1/vocab/filter-by-status`` with ``{unknown, seen}``, matched
**lemma-only** so a dict-vs-Sudachi reading mismatch can't resurrect a known word).
Those survivors are what the wiring layer turns into Lapis word notes - this op is
just the backend composition (it creates no notes itself; deduping against existing
notes and copying context fields needs ``mw.col`` and happens on the UI thread).

Very common kana-only lemmas (JPDB rank below ``min_kana_rank``) are dropped too:
at that frequency a kana word is a function word or auxiliary, not vocab worth a
card. The filter lives in THIS module, on the generation path only - kana words
still count as vocab for n+1 sentence scoring, so dropping them at extraction
(beside ``is_pure_katakana`` in the backend) would inflate every sentence's
known-word count.

Targets (the word deck + its note type), the on-existing policy and that rank floor
are params, so the whole thing reuses the pipeline machinery (config, params dialog,
validation, "Run now", auto-run-on-start) with no separate feature wiring.
"""

from ..client import BackendClient
from ..config import ALIASES
from .base import GenerateOperation, ParamSpec
from .nplus1 import strip_markup

# Fields this op SEEDS itself on the new note; never treated as copied context.
# Lives here rather than in :mod:`jp_utils.generation` so that module (which needs
# it, and already reaches into ops for `strip_markup`) can import it without the
# ops package having to import back.
SEED_ALIASES = ("word", "word-reading")

# Every alias is offerable in the copy whitelist; an entry only copies when actually
# mapped on both note types and not a seed (see :func:`jp_utils.generation.context_aliases`).
# Default-checked: the sentence-context fields (the ``sentence*`` aliases), which is what
# usually carries onto a word card. The seeds (`word`, `word-reading`) are LOCKED on: the
# op writes them itself, so listing them unchecked would suggest they can be opted out of.
CONTEXT_ALIAS_CHOICES = ALIASES
DEFAULT_CONTEXT_ALIASES = tuple(a for a in ALIASES if a.startswith("sentence"))

# Default kana-only cutoff (JPDB rank, lower = more frequent); the `min_kana_rank`
# param overrides it.
_DEFAULT_MIN_KANA_RANK = 2000

# "Kana only" = hiragana/katakana letters plus the prolonged sound mark and middle
# dot, with at least one real kana (so a bare "ー" is not a kana word). Mirrors the
# backend's `is_pure_katakana`, widened to hiragana.
_KANA_LETTERS = frozenset(chr(c) for c in [*range(0x3041, 0x3097), *range(0x30A1, 0x30FB)])
_KANA_EXTRA = frozenset("ー・ゝゞヽヾ゛゜")


def is_kana_only(text: str) -> bool:
    """True when ``text`` is written purely in kana (no kanji, no latin, no digits)."""
    has_letter = False
    for ch in text:
        if ch in _KANA_LETTERS:
            has_letter = True
        elif ch not in _KANA_EXTRA:
            return False
    return has_letter


def _rank_floor(params: dict | None) -> int:
    """The step's `min_kana_rank`, or the default when unset/blank/non-numeric."""
    raw = str((params or {}).get("min_kana_rank", "")).strip()
    if not raw:
        return _DEFAULT_MIN_KANA_RANK
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_MIN_KANA_RANK


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
    locked_choices=SEED_ALIASES,
    description="Sentence-context aliases to copy onto the new card (each only copies when "
    "mapped on both note types). Unchecked means copy nothing; word and word-reading are "
    "always seeded regardless.",
)
MIN_KANA_RANK = ParamSpec(
    "min_kana_rank",
    "Kana-only frequency floor",
    "text",
    default=str(_DEFAULT_MIN_KANA_RANK),
    description="A kana-only word ranked more frequent than this JPDB rank is not turned "
    "into a card. Unranked kana words are kept. 0 disables the filter.",
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
    params_spec = (TARGET_DECK, TARGET_NOTE_TYPE, ON_EXISTING, COPY_ALIASES, MIN_KANA_RANK)

    def generate(
        self,
        client: BackendClient,
        sources: list[dict[str, str]],
        params: dict | None = None,
    ) -> list[list[dict]]:
        texts = [strip_markup(s.get("sentence", "")) for s in sources]
        resp = client.post("/v1/text/content-words", {"texts": texts})
        results = resp.get("results", [])
        # Align to sources; each entry is a list of {"lemma", "reading"} dicts.
        word_lists = [results[i] if i < len(results) else [] for i in range(len(sources))]

        # One entry per distinct lemma: the same word turns up across many mined
        # sentences, and the filter answers by lemma anyway - so sending every
        # occurrence would inflate the request several-fold over a full sweep for
        # an identical answer.
        candidates = {
            w["lemma"]: w for word_list in word_lists for w in word_list if w.get("lemma")
        }
        if not candidates:
            return [[] for _ in sources]

        # One batched status filter over every candidate; keep new words only.
        filtered = client.post(
            "/v1/vocab/filter-by-status",
            {
                "words": list(candidates.values()),
                "statuses": ["unknown", "seen"],
                "match_lemma_only": True,
            },
        )
        kept_lemmas = {w["lemma"] for w in filtered.get("matched", [])}
        kept_lemmas -= self._common_kana_lemmas(
            client,
            [w for lemma, w in candidates.items() if lemma in kept_lemmas],
            params,
        )
        return [[w for w in word_list if w["lemma"] in kept_lemmas] for word_list in word_lists]

    def _common_kana_lemmas(
        self, client: BackendClient, kept: list[dict], params: dict | None
    ) -> set[str]:
        """The kana-only lemmas among ``kept`` common enough to skip (rank < the floor).

        Only kana-only survivors are looked up; a kanji word never qualifies. An
        unranked word is kept - unranked means rare, i.e. a real adverb or verb that
        happens to be written in kana.
        """
        floor = _rank_floor(params)
        if floor <= 0:
            return set()
        kana = [w for w in kept if is_kana_only(w["lemma"])]
        if not kana:
            return set()
        resp = client.post(
            "/v1/text/frequency",
            {"queries": [{"term": w["lemma"], "reading": w.get("reading", "")} for w in kana]},
        )
        results = resp.get("results", [])
        skip = set()
        for word, result in zip(kana, results, strict=False):  # short result = no rank
            rank = result.get("rank")
            if rank is not None and rank < floor:
                skip.add(word["lemma"])
        return skip
