"""Tail rules and span reduction - the pieces normalize and locate share."""

import pytest

from app.text.inflection import (
    absorbed_end,
    deinflect,
    is_inflection_tail,
    is_word_head,
    strip_tails,
)
from app.text.tokenizer import Tokenizer


def _tok(tokenizer: Tokenizer, text: str):
    return tokenizer.tokenize(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("食べた", ["た"]),  # 助動詞
        ("食べている", ["て", "いる"]),  # allowlisted 接続助詞 + 非自立可能 verb
        ("食べたり", ["たり"]),  # 副助詞, but stem-attaching
        ("歩きながら", ["ながら"]),
    ],
)
def test_stem_attaching_morphemes_are_tails(
    tokenizer: Tokenizer, text: str, expected: list[str]
) -> None:
    tails = [t.surface for t in _tok(tokenizer, text) if is_inflection_tail(t)]
    assert tails == expected


@pytest.mark.parametrize(
    "text", ["惜しかったけど", "傷ついてるから", "駆けつけたかったが", "蘇ってくるし"]
)
def test_clause_level_particles_are_not_tails(tokenizer: Tokenizer, text: str) -> None:
    # から / が / けど / し attach to a finished clause, so they end the word.
    assert not is_inflection_tail(_tok(tokenizer, text)[-1])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("猫", True),
        ("お茶", True),  # 接頭辞 can begin a word
        ("走る", True),
        ("。", False),  # 補助記号
        ("ました", False),  # bare 助動詞
        ("だます", False),  # misparsed as copula だ + ます
    ],
)
def test_is_word_head(tokenizer: Tokenizer, text: str, expected: bool) -> None:
    assert is_word_head(_tok(tokenizer, text)[0]) is expected


def test_strip_tails_keeps_the_head(tokenizer: Tokenizer) -> None:
    # Every morpheme of ました is a tail; the head is still never stripped.
    assert [t.surface for t in strip_tails(_tok(tokenizer, "ました"))] == ["まし"]


def test_strip_tails_drops_a_particle_a_dropped_tail_exposed(tokenizer: Tokenizer) -> None:
    # ご覧になる -> ご覧 + に + なる. Dropping なる leaves に dangling, and a
    # particle cannot end a word, so it goes too.
    assert [t.surface for t in strip_tails(_tok(tokenizer, "ご覧になる"))] == ["ご覧"]


def test_strip_tails_keeps_a_particle_the_word_ends_on(tokenizer: Tokenizer) -> None:
    # Nothing was stripped from 次第に, so its trailing に stays - it is part of
    # the word, not the residue of one.
    assert [t.surface for t in strip_tails(_tok(tokenizer, "次第に"))] == ["次第", "に"]


@pytest.mark.parametrize(
    ("surface", "lemma", "reading"),
    [
        ("食べた", "食べる", "タベル"),  # deinflects
        ("食べさせられた", "食べる", "タベル"),  # through a causative-passive stack
        ("記憶喪失", "記憶喪失", "キオクソウシツ"),  # compound stays whole
        ("お茶", "お茶", "オチャ"),  # prefix stays attached
        ("上等", "上等", "ジョウトウ"),  # noun + suffix stays whole
        ("足元をすくう", "足元をすくう", "アシモトヲスクウ"),  # a phrasal entry
        ("猫", "猫", "ネコ"),
    ],
)
def test_deinflect_folds_the_span_and_conjugates_only_its_end(
    tokenizer: Tokenizer, surface: str, lemma: str, reading: str
) -> None:
    got_lemma, got_reading, _ = deinflect(tokenizer, _tok(tokenizer, surface))
    assert (got_lemma, got_reading) == (lemma, reading)


@pytest.mark.parametrize(
    ("sentence", "word", "expected"),
    [
        # 動詞 / 形容詞 heads absorb their whole conjugation...
        ("ご飯を食べている", "食べる", "食べている"),
        # ...but stop at a particle that attaches to a finished clause.
        ("残念だね〜惜しかったけど", "惜しい", "惜しかった"),
        # A copula is not part of a plain noun.
        ("俺は新人だ", "新人", "新人"),
        # 行く / ある are 非自立可能 by possibility, not by use.
        ("保健室行くところ", "保健室", "保健室"),
        ("たくさんあるんだから", "たくさん", "たくさん"),
        # A na-adjective DOES inflect through the copula.
        ("広大な大陸", "広大", "広大な"),
        # A サ変 noun absorbs the light verb that is its own verb form.
        ("こいつらを攻略していた", "攻略", "攻略していた"),
        ("好きを共有できる", "共有", "共有できる"),
        # ...but a helper verb after a noun+copula starts a new word.
        ("挑発されて本気になった", "本気", "本気"),
    ],
)
def test_absorbed_end_is_head_aware(
    tokenizer: Tokenizer, sentence: str, word: str, expected: str
) -> None:
    tokens = _tok(tokenizer, sentence)
    i = next(
        i
        for i, t in enumerate(tokens)
        if t.dictionary_form == word or sentence[t.start :].startswith(word)
    )
    assert sentence[tokens[i].start : absorbed_end(tokens, i)] == expected
