"""Tests for the pure generation helpers (copy-set derivation, dedup key)."""

from jp_utils.generation import context_aliases, should_write, word_key
from jp_utils.ops.generate import COPY_ALIASES, SEED_ALIASES


def test_context_aliases_copies_shared_minus_seeds():
    source = {
        "sentence": "Sentence",
        "sentence-audio": "SentenceAudio",
        "sentence-meaning": "SentEng",
        "word": "Expression",  # a seed: never copied
    }
    target = {
        "sentence": "Sentence",
        "sentence-audio": "SentenceAudio",
        "sentence-meaning": "Glossary",
        "word": "Expression",
    }

    # sentence + sentence-audio + sentence-meaning map on both and aren't seeds.
    assert context_aliases(source, target) == [
        "sentence",
        "sentence-audio",
        "sentence-meaning",
    ]


def test_context_aliases_whitelist_restricts_copy_set():
    source = {"sentence": "S", "sentence-audio": "SentenceAudio", "sentence-meaning": "SentEng"}
    target = {"sentence": "S", "sentence-audio": "SentenceAudio", "sentence-meaning": "Glossary"}

    # Only the whitelisted (and still-eligible) aliases come through.
    assert context_aliases(source, target, ["sentence-audio", "sentence-meaning"]) == [
        "sentence-audio",
        "sentence-meaning",
    ]


def test_context_aliases_empty_whitelist_copies_nothing():
    source = {"sentence": "Sentence", "sentence-audio": "SentenceAudio"}
    target = {"sentence": "Sentence", "sentence-audio": "SentenceAudio"}
    assert context_aliases(source, target, []) == []


def test_context_aliases_none_whitelist_copies_all_eligible():
    source = {"sentence": "Sentence", "sentence-audio": "SentenceAudio"}
    target = {"sentence": "Sentence", "sentence-audio": "SentenceAudio"}
    assert context_aliases(source, target, None) == ["sentence", "sentence-audio"]


def test_context_aliases_requires_mapping_on_both_sides():
    source = {"sentence-audio": "SentenceAudio"}  # only on source
    target = {"sentence": "Sentence"}  # only on target
    assert context_aliases(source, target) == []


def test_context_aliases_skips_blank_field_bindings():
    source = {"sentence": "Sentence", "sentence-meaning": ""}  # blank binding
    target = {"sentence": "Sentence", "sentence-meaning": "Glossary"}
    assert context_aliases(source, target) == ["sentence"]


def test_word_key_strips_markup_from_both_sides():
    # An existing note whose word field carries ruby still matches the plain lemma.
    assert word_key("<ruby>猫<rt>ねこ</rt></ruby>", "ねこ") == word_key("猫", "ねこ")
    assert word_key("<b>猫</b>&nbsp;", "") == ("猫", "")


def test_word_key_keeps_homographs_apart():
    assert word_key("辛い", "からい") != word_key("辛い", "つらい")


def test_copy_whitelist_locks_the_seeded_aliases():
    # The op writes the seeds itself, so the copy list offers them permanently
    # checked - and copying them is still a no-op even when they arrive whitelisted.
    assert COPY_ALIASES.locked_choices == SEED_ALIASES
    assert set(SEED_ALIASES) <= set(COPY_ALIASES.choices)
    mapping = {"word": "Expression", "word-reading": "Reading"}
    assert context_aliases(mapping, mapping, list(SEED_ALIASES)) == []


def test_should_write_skips_an_identical_value():
    # Idempotency: re-running a generation over the same source changes nothing.
    assert should_write("猫が好き", "猫が好き", only_if_empty=False) is False
    assert should_write("猫が好き", "猫が好き", only_if_empty=True) is False


def test_should_write_overwrites_only_when_not_filling():
    # `overwrite` refreshes a differing value; `fill` protects the hand edit.
    assert should_write("my own sentence", "the source sentence", only_if_empty=False) is True
    assert should_write("my own sentence", "the source sentence", only_if_empty=True) is False


def test_should_write_populates_an_empty_field_in_both_modes():
    assert should_write("", "猫が好き", only_if_empty=True) is True
    assert should_write("", "猫が好き", only_if_empty=False) is True


def test_should_write_treats_stray_markup_as_content():
    # Emptiness is plain falsiness, as for every other op's only_if_empty.
    assert should_write("<br>", "猫が好き", only_if_empty=True) is False
