"""The lemma-collapse gate: which forms are words and which are inflection residue."""

import pytest

from app.text.canonical import CANONICAL_MAX_RANK, canonical_lemma
from app.text.tokenizer import Tokenizer


class FakeDicts:
    """The two lookups `canonical_lemma` uses, over a hand-written rank table.

    Each term maps to `(as-written rank, kana-spelling rank)`, as JPDB gives them.
    """

    def __init__(self, ranks: dict[str, tuple[int | None, int | None]]) -> None:
        self._ranks = ranks

    def lookup_frequency(self, term: str, reading: str | None = None) -> int | None:
        written, kana = self._ranks.get(term, (None, None))
        return written if written is not None else kana

    def lookup_spelling_ranks(self, term: str) -> tuple[int | None, int | None]:
        return self._ranks.get(term, (None, None))


@pytest.fixture
def dicts() -> FakeDicts:
    # 作れる / 子ども are unranked residue; 捜す is a ranked variant of 探す.
    # 省く is written the normal way but uncommon; 迚も is an archaic spelling of
    # a very common word; 鮟鱇 has no kana figure to be compared against.
    return FakeDicts(
        {
            "作る": (140, 2763),
            "子供": (422, 23368),
            "捜す": (2123, 12703),
            "探す": (421, 12703),
            "鮟鱇": (119997, None),
            "省く": (10363, 48758),
            "迚も": (152585, 329),
            "ちっ": (None, 2831),
        }
    )


def test_unranked_potential_form_collapses(tokenizer: Tokenizer, dicts: FakeDicts) -> None:
    # The base's reading replaces the form's: ツクレル describes 作れる, not 作る.
    assert canonical_lemma(tokenizer, dicts, "作れる", "ツクレル", "作る") == ("作る", "ツクル")


def test_unranked_orthographic_variant_collapses(tokenizer: Tokenizer, dicts: FakeDicts) -> None:
    assert canonical_lemma(tokenizer, dicts, "子ども", "コドモ", "子供")[0] == "子供"


def test_ranked_form_is_a_word_in_its_own_right(tokenizer: Tokenizer, dicts: FakeDicts) -> None:
    # 捜す normalizes to 探す but has a rank of its own, so a card spelling it
    # 捜す keeps that key: the store holds a word as the card spells it.
    assert canonical_lemma(tokenizer, dicts, "捜す", "サガス", "探す") == ("捜す", "サガス")


def test_base_over_the_ceiling_with_nothing_to_compare_is_refused(
    tokenizer: Tokenizer, dicts: FakeDicts
) -> None:
    # Collapsing onto a spelling nobody writes trades one dead key for another,
    # and with no kana figure the ceiling is the only evidence there is.
    assert dicts.lookup_spelling_ranks("鮟鱇") == (119997, None)
    assert canonical_lemma(tokenizer, dicts, "あんこう", "アンコウ", "鮟鱇")[0] == "あんこう"


def test_uncommon_word_written_the_normal_way_collapses(
    tokenizer: Tokenizer, dicts: FakeDicts
) -> None:
    # 省く is far over the ceiling, but it beats its own kana spelling, so it is
    # an uncommon word rather than an archaic spelling of a common one.
    written, kana = dicts.lookup_spelling_ranks("省く")
    assert written > CANONICAL_MAX_RANK and written < kana
    assert canonical_lemma(tokenizer, dicts, "省ける", "ハブケル", "省く")[0] == "省く"


def test_archaic_spelling_of_a_common_word_is_refused(
    tokenizer: Tokenizer, dicts: FakeDicts
) -> None:
    # とても is what gets written, so 迚も is worthless as a vocabulary key -
    # exactly the case a single rank cannot tell from 省く above.
    assert canonical_lemma(tokenizer, dicts, "とっても", "トッテモ", "迚も")[0] == "とっても"


def test_base_ranked_only_through_its_kana_spelling_collapses(
    tokenizer: Tokenizer, dicts: FakeDicts
) -> None:
    # A kana headword has no as-written figure; the ceiling decides on the one
    # number there is.
    assert canonical_lemma(tokenizer, dicts, "チッ", "チッ", "ちっ")[0] == "ちっ"


def test_unranked_base_is_refused(tokenizer: Tokenizer, dicts: FakeDicts) -> None:
    assert canonical_lemma(tokenizer, dicts, "ねぇ", "ネェ", "ねえ")[0] == "ねぇ"


def test_form_that_is_already_its_own_base(tokenizer: Tokenizer, dicts: FakeDicts) -> None:
    assert canonical_lemma(tokenizer, dicts, "作る", "ツクル", "作る") == ("作る", "ツクル")


def test_without_a_dict_cache_nothing_collapses(tokenizer: Tokenizer) -> None:
    # No gate available, so the rule cannot tell residue from a real word.
    assert canonical_lemma(tokenizer, None, "作れる", "ツクレル", "作る") == ("作れる", "ツクレル")
