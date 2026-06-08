"""Tests for the pure generation helpers (copy-set derivation, dedup key)."""

from jp_utils.generation import context_aliases, word_key


def test_context_aliases_copies_shared_minus_seeds():
    source = {
        "sentence": "Sentence",
        "sentence-audio": "SentenceAudio",
        "alt-definition": "SentEng",
        "word": "Expression",  # a seed: never copied
    }
    target = {
        "sentence": "Sentence",
        "sentence-audio": "SentenceAudio",
        "alt-definition": "Glossary",
        "word": "Expression",
    }

    # sentence + sentence-audio + alt-definition map on both and aren't seeds.
    assert context_aliases(source, target) == [
        "alt-definition",
        "sentence",
        "sentence-audio",
    ]


def test_context_aliases_requires_mapping_on_both_sides():
    source = {"sentence-audio": "SentenceAudio"}  # only on source
    target = {"sentence": "Sentence"}  # only on target
    assert context_aliases(source, target) == []


def test_context_aliases_skips_blank_field_bindings():
    source = {"sentence": "Sentence", "alt-definition": ""}  # blank binding
    target = {"sentence": "Sentence", "alt-definition": "Glossary"}
    assert context_aliases(source, target) == ["sentence"]


def test_word_key_strips_markup_from_both_sides():
    # An existing note whose word field carries ruby still matches the plain lemma.
    assert word_key("<ruby>猫<rt>ねこ</rt></ruby>", "ねこ") == word_key("猫", "ねこ")
    assert word_key("<b>猫</b>&nbsp;", "") == ("猫", "")


def test_word_key_keeps_homographs_apart():
    assert word_key("辛い", "からい") != word_key("辛い", "つらい")
