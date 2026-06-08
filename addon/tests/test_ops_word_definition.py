"""Tests for the word-definition operation (request shape + sense formatting)."""

from jp_utils.ops.word_definition import (
    FORMAT_COMPRESSED,
    FORMAT_EXPANDED,
    WordDefinitionOperation,
)


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        return self.response


# One headword with two senses; sense 1 has POS + an example, sense 2 is plain.
_RESULT = {
    "results": [
        {
            "lemma": "猫",
            "all_readings": ["ねこ", "びょう"],
            "entries": [
                {
                    "senses": [
                        {
                            "pos": ["noun"],
                            "glosses": ["cat"],
                            "examples": [{"ja": "猫がいる", "en": "there is a cat"}],
                        },
                        {"pos": ["noun"], "glosses": ["tomcat", "puss"], "examples": []},
                    ],
                }
            ],
        }
    ]
}


def _run(params, result=_RESULT):
    return WordDefinitionOperation().compute(
        _FakeClient(result), [{"word": "猫", "word-reading": "ねこ"}], params
    )


def test_builds_lemma_queries():
    client = _FakeClient(_RESULT)
    WordDefinitionOperation().compute(
        client, [{"word": "猫", "word-reading": "ねこ"}], {"format": FORMAT_COMPRESSED}
    )
    assert client.calls == [("/v1/text/meaning", {"queries": [{"lemma": "猫", "reading": "ねこ"}]})]


def test_compressed_joins_glosses_per_sense():
    assert _run({"format": FORMAT_COMPRESSED}) == ["<ol><li>cat</li><li>tomcat; puss</li></ol>"]


def test_expanded_one_bullet_per_gloss():
    assert _run({"format": FORMAT_EXPANDED}) == [
        "<ol><li><ul><li>cat</li></ul></li><li><ul><li>tomcat</li><li>puss</li></ul></li></ol>"
    ]


def test_default_format_is_expanded():
    assert _run({}) == _run({"format": FORMAT_EXPANDED})


def test_include_pos_prefixes_each_sense():
    assert _run({"format": FORMAT_COMPRESSED, "include_pos": True}) == [
        "<ol><li>[noun] cat</li><li>[noun] tomcat; puss</li></ol>"
    ]


def test_include_examples_renders_one_per_sense():
    assert _run({"format": FORMAT_COMPRESSED, "include_examples": True}) == [
        "<ol><li>cat<div>猫がいる</div><div>there is a cat</div></li><li>tomcat; puss</li></ol>"
    ]


def test_readings_trail_with_word_label():
    assert _run({"format": FORMAT_COMPRESSED, "include_readings": True}) == [
        "<ol><li>cat</li><li>tomcat; puss</li></ol><div>猫 readings: ねこ, びょう</div>"
    ]


_SINGLE = {
    "results": [
        {
            "lemma": "猫",
            "all_readings": ["ねこ"],
            "entries": [{"senses": [{"pos": ["noun"], "glosses": ["cat"], "examples": []}]}],
        }
    ]
}


def test_single_sense_compressed_still_in_ol():
    assert _run({"format": FORMAT_COMPRESSED}, _SINGLE) == ["<ol><li>cat</li></ol>"]


def test_single_sense_expanded_still_in_ol():
    assert _run({"format": FORMAT_EXPANDED}, _SINGLE) == ["<ol><li><ul><li>cat</li></ul></li></ol>"]


def test_single_sense_keeps_pos_and_readings():
    assert _run({"include_pos": True, "include_readings": True}, _SINGLE) == [
        "<ol><li>[noun] <ul><li>cat</li></ul></li></ol><div>猫 readings: ねこ</div>"
    ]


def test_no_senses_leaves_field_unchanged():
    result = {"results": [{"all_readings": [], "entries": [{"senses": []}]}]}
    assert _run({"format": FORMAT_COMPRESSED}, result) == [None]


def test_both_word_and_reading_are_required():
    op = WordDefinitionOperation()
    assert op.applicable({"word": "猫", "word-reading": "ねこ"})
    assert not op.applicable({"word": "猫", "word-reading": ""})  # reading required
    assert not op.applicable({"word": "", "word-reading": "ねこ"})
