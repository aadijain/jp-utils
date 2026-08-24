"""The lemma-collapse gate: which forms are words and which are inflection residue."""

import pytest

from app.text.canonical import CANONICAL_MAX_RANK, canonical_lemma
from app.text.tokenizer import Tokenizer


class FakeDicts:
    """Just the one lookup `canonical_lemma` uses, with a hand-written rank table."""

    def __init__(self, ranks: dict[str, int]) -> None:
        self._ranks = ranks

    def lookup_frequency(self, term: str, reading: str | None = None) -> int | None:
        return self._ranks.get(term)


@pytest.fixture
def dicts() -> FakeDicts:
    # 作れる / 子ども are unranked residue; 捜す is a ranked variant of 探す.
    return FakeDicts({"作る": 140, "子供": 422, "捜す": 2123, "探す": 421, "鮟鱇": 119997})


def test_unranked_potential_form_collapses(tokenizer: Tokenizer, dicts: FakeDicts) -> None:
    # The base's reading replaces the form's: ツクレル describes 作れる, not 作る.
    assert canonical_lemma(tokenizer, dicts, "作れる", "ツクレル", "作る") == ("作る", "ツクル")


def test_unranked_orthographic_variant_collapses(tokenizer: Tokenizer, dicts: FakeDicts) -> None:
    assert canonical_lemma(tokenizer, dicts, "子ども", "コドモ", "子供")[0] == "子供"


def test_ranked_form_is_a_word_in_its_own_right(tokenizer: Tokenizer, dicts: FakeDicts) -> None:
    # 捜す normalizes to 探す but has a rank of its own, so a card spelling it
    # 捜す keeps that key: the store holds a word as the card spells it.
    assert canonical_lemma(tokenizer, dicts, "捜す", "サガス", "探す") == ("捜す", "サガス")


def test_base_over_the_ceiling_is_refused(tokenizer: Tokenizer, dicts: FakeDicts) -> None:
    # Collapsing onto a spelling nobody writes trades one dead key for another.
    assert dicts.lookup_frequency("鮟鱇") > CANONICAL_MAX_RANK
    assert canonical_lemma(tokenizer, dicts, "あんこう", "アンコウ", "鮟鱇")[0] == "あんこう"


def test_unranked_base_is_refused(tokenizer: Tokenizer, dicts: FakeDicts) -> None:
    assert canonical_lemma(tokenizer, dicts, "ねぇ", "ネェ", "ねえ")[0] == "ねぇ"


def test_form_that_is_already_its_own_base(tokenizer: Tokenizer, dicts: FakeDicts) -> None:
    assert canonical_lemma(tokenizer, dicts, "作る", "ツクル", "作る") == ("作る", "ツクル")


def test_without_a_dict_cache_nothing_collapses(tokenizer: Tokenizer) -> None:
    # No gate available, so the rule cannot tell residue from a real word.
    assert canonical_lemma(tokenizer, None, "作れる", "ツクレル", "作る") == ("作れる", "ツクレル")
