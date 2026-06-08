"""Tests for the word-definition operation (request shape + gloss formatting)."""

from jp_utils.ops.word_definition import WordDefinitionOperation


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        return self.response


def test_builds_lemma_queries_and_bullets_glosses():
    client = _FakeClient(
        {
            "results": [
                {"entries": [{"glosses": ["cat"]}, {"glosses": ["tomcat", "puss"]}]},
                {"entries": []},
            ]
        }
    )
    out = WordDefinitionOperation().compute(
        client, [{"word": "猫", "word-reading": "ねこ"}, {"word": "zzz", "word-reading": "zzz"}]
    )
    assert out == ["<ul><li>cat</li><li>tomcat</li><li>puss</li></ul>", None]
    assert client.calls == [
        (
            "/v1/text/meaning",
            {"queries": [{"lemma": "猫", "reading": "ねこ"}, {"lemma": "zzz", "reading": "zzz"}]},
        )
    ]


def test_empty_glosses_leave_field_unchanged():
    out = WordDefinitionOperation().compute(
        _FakeClient({"results": [{"entries": [{"glosses": []}]}]}),
        [{"word": "猫", "word-reading": "ねこ"}],
    )
    assert out == [None]


def test_glosses_are_html_escaped():
    # Real jitendex glosses contain raw markup characters ("less-than mark (<)");
    # they must land in the field as entities, not as broken HTML.
    out = WordDefinitionOperation().compute(
        _FakeClient({"results": [{"entries": [{"glosses": ["less-than mark (<)", "S&M"]}]}]}),
        [{"word": "小なり", "word-reading": "しょうなり"}],
    )
    assert "less-than mark (&lt;)" in out[0]
    assert "S&amp;M" in out[0]


def test_both_word_and_reading_are_required():
    op = WordDefinitionOperation()
    assert op.applicable({"word": "猫", "word-reading": "ねこ"})
    assert not op.applicable({"word": "猫", "word-reading": ""})  # reading required
    assert not op.applicable({"word": "", "word-reading": "ねこ"})
