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


def test_context_aliases_requires_mapping_on_both_sides():
    source = {"sentence-audio": "SentenceAudio"}  # only on source
    target = {"sentence": "Sentence"}  # only on target
    assert context_aliases(source, target) == []


def test_context_aliases_skips_blank_field_bindings():
    source = {"sentence": "Sentence", "alt-definition": ""}  # blank binding
    target = {"sentence": "Sentence", "alt-definition": "Glossary"}
    assert context_aliases(source, target) == ["sentence"]
