"""The lemma-collapse gate: which forms are words and which are inflection residue."""

import pytest

from app.dicts import Spellings
from app.text.canonical import (
    CANONICAL_MAX_RANK,
    KANA_SPELLING_MARGIN,
    canonical_lemma,
    written_spelling,
)
from app.text.tokenizer import Tokenizer


class FakeDicts:
    """The two lookups this module uses, over a hand-written rank table.

    Each term maps to `(as-written rank, kana-spelling rank, kana spelling)`, as
    JPDB gives them.
    """

    def __init__(self, ranks: dict[str, Spellings]) -> None:
        self._ranks = ranks

    def lookup_frequency(self, term: str, reading: str | None = None) -> int | None:
        sp = self._ranks.get(term, Spellings(None, None, None))
        return sp.written if sp.written is not None else sp.kana

    def lookup_spellings(self, term: str) -> Spellings:
        return self._ranks.get(term, Spellings(None, None, None))


@pytest.fixture
def dicts() -> FakeDicts:
    # 作れる / 子ども are unranked residue; 捜す is a ranked variant of 探す.
    # 省く is written the normal way but uncommon; 迚も is an archaic spelling of
    # a very common word; 鮟鱇 has no kana figure to be compared against.
    # 貰う is written both ways, with もらう the one that wins; 嵌まる is written
    # both ways too but not by enough to lose the key.
    return FakeDicts(
        {
            "作る": Spellings(140, 2763, "つくる"),
            "子供": Spellings(422, 23368, "こども"),
            "捜す": Spellings(2123, 12703, "さがす"),
            "探す": Spellings(421, 12703, "さがす"),
            "鮟鱇": Spellings(119997, None, None),
            "省く": Spellings(10363, 48758, "はぶく"),
            "迚も": Spellings(152585, 329, "とても"),
            "ちっ": Spellings(None, 2831, "ちっ"),
            "貰う": Spellings(1295, 112, "もらう"),
            "嵌まる": Spellings(23785, 6041, "はまる"),
            "べい": Spellings(None, 93514, "べい"),
            "菱": Spellings(None, 40000, "ひし"),
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
    assert dicts.lookup_spellings("鮟鱇") == Spellings(119997, None, None)
    assert canonical_lemma(tokenizer, dicts, "あんこう", "アンコウ", "鮟鱇")[0] == "あんこう"


def test_uncommon_word_written_the_normal_way_collapses(
    tokenizer: Tokenizer, dicts: FakeDicts
) -> None:
    # 省く is far over the ceiling, but it beats its own kana spelling, so it is
    # an uncommon word rather than an archaic spelling of a common one.
    spellings = dicts.lookup_spellings("省く")
    assert spellings.written > CANONICAL_MAX_RANK and spellings.written < spellings.kana
    assert canonical_lemma(tokenizer, dicts, "省ける", "ハブケル", "省く")[0] == "省く"


def test_archaic_spelling_loses_the_key_to_the_kana_spelling(
    tokenizer: Tokenizer, dicts: FakeDicts
) -> None:
    # とても is what gets written, so 迚も is worthless as a vocabulary key -
    # exactly the case a single rank cannot tell from 省く above. Refusing the
    # collapse would leave とっても its own word; the row names the key instead.
    assert canonical_lemma(tokenizer, dicts, "とっても", "トッテモ", "迚も") == ("とても", "トテモ")


def test_kana_spelling_takes_the_key_from_a_base_it_routs(
    tokenizer: Tokenizer, dicts: FakeDicts
) -> None:
    # 貰う has an ordinary as-written rank, so the ceiling and the
    # written-beats-kana test would both hand it the key. もらう routing it is the
    # only evidence that says otherwise.
    assert canonical_lemma(tokenizer, dicts, "もらえる", "モラエル", "貰う")[0] == "もらう"


def test_kana_spelling_that_does_not_rout_the_base_leaves_the_key_alone(
    tokenizer: Tokenizer, dicts: FakeDicts
) -> None:
    # はまる beats 嵌まる, but not by the margin: a word written both ways does not
    # give the kana spelling the key on a narrow win. Neither spelling qualifies
    # here, so the form keeps its own key.
    spellings = dicts.lookup_spellings("嵌まる")
    assert spellings.kana * KANA_SPELLING_MARGIN > spellings.written
    assert canonical_lemma(tokenizer, dicts, "ハマる", "ハマル", "嵌まる")[0] == "ハマる"


def test_base_ranked_only_in_kana_takes_the_kana_spelling_over_the_ceiling(
    tokenizer: Tokenizer, dicts: FakeDicts
) -> None:
    # べい is far over the ceiling, but JPDB ranks the word in kana and nowhere
    # else, so there is no rival spelling for the ceiling to be protecting.
    assert canonical_lemma(tokenizer, dicts, "べ", "ベ", "べい")[0] == "べい"


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


def test_written_spelling_answers_for_a_key_jpdb_pairs_with_it(dicts: FakeDicts) -> None:
    # もらう has no jitendex entry, and 貰う - the spelling the collapse overrode -
    # is the same word, because JPDB spells 貰う もらう.
    assert written_spelling(dicts, "もらう", "貰う") == "貰う"


def test_written_spelling_refuses_a_normalization_onto_a_different_word(
    dicts: FakeDicts,
) -> None:
    # Sudachi normalizes びし onto 菱, but 菱 reads ひし: a different word, and
    # serving its definition would be worse than serving none.
    assert written_spelling(dicts, "びし", "菱") is None


def test_written_spelling_has_nothing_to_offer_a_form_that_is_its_own_base(
    dicts: FakeDicts,
) -> None:
    assert written_spelling(dicts, "べい", "べい") is None
