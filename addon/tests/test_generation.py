"""Tests for the pure generation helpers (copy-set derivation)."""

from jp_utils.generation import context_aliases


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


def test_context_aliases_whitelist_restricts_copy_set():
    source = {"sentence": "S", "sentence-audio": "SentenceAudio", "alt-definition": "SentEng"}
    target = {"sentence": "S", "sentence-audio": "SentenceAudio", "alt-definition": "Glossary"}

    # Only the whitelisted (and still-eligible) aliases come through.
    assert context_aliases(source, target, ["sentence-audio", "alt-definition"]) == [
        "alt-definition",
        "sentence-audio",
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
    source = {"sentence": "Sentence", "alt-definition": ""}  # blank binding
    target = {"sentence": "Sentence", "alt-definition": "Glossary"}
    assert context_aliases(source, target) == ["sentence"]
