"""Tests for the word-definition operation (request shape + sense formatting)."""

from jp_utils.ops.word_definition import (
    _CHIP_STYLE,
    _CONTAINER_STYLE,
    _EXAMPLE_BOX_STYLE,
    _EXAMPLE_EN_STYLE,
    _GLOSS_UL_STYLE,
    _HIGHLIGHT_STYLE,
    _MARKER_STYLE,
    _READINGS_CHIP_STYLE,
    _READINGS_STYLE,
    _READINGS_VAL_STYLE,
    _SENSE_LI_STYLE,
    _SENSE_OL_STYLE,
    FORMAT_COMPRESSED,
    FORMAT_EXPANDED,
    WordDefinitionOperation,
)


def _wrap(body: str) -> str:
    """The container the op wraps every (non-empty) definition in."""
    return f'<div class="jpu-definition" style="{_CONTAINER_STYLE}">{body}</div>'


def _marker(n: int) -> str:
    return f'<span style="{_MARKER_STYLE}">{chr(0x2460 + n - 1)}</span>'


def _ol(*items: str) -> str:
    lis = "".join(
        f'<li style="{_SENSE_LI_STYLE}">{_marker(n)}{item}</li>' for n, item in enumerate(items, 1)
    )
    return f'<ol style="{_SENSE_OL_STYLE}">{lis}</ol>'


def _chip(text: str) -> str:
    return f'<span style="{_CHIP_STYLE}">{text}</span>'


def _readings(*rs: str) -> str:
    """The labelled Readings chip row appended when include_readings is on."""
    return (
        f'<div style="{_READINGS_STYLE}">'
        f'<span style="{_READINGS_CHIP_STYLE}">Readings</span>'
        f'<span style="{_READINGS_VAL_STYLE}">{", ".join(rs)}</span></div>'
    )


def _gloss_ul(*glosses: str) -> str:
    lis = "".join(f"<li>{g}</li>" for g in glosses)
    return f'<ul style="{_GLOSS_UL_STYLE}">{lis}</ul>'


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
    assert _run({"format": FORMAT_COMPRESSED}) == [_wrap(_ol("cat", "tomcat | puss"))]


def test_senses_carry_circled_markers_not_native_numbering():
    out = _run({"format": FORMAT_COMPRESSED})[0]
    assert "①" in out and "②" in out  # circled sense markers
    assert "list-style:none" in out  # native numbering disabled


def test_expanded_one_bullet_per_gloss():
    assert _run({"format": FORMAT_EXPANDED}) == [
        _wrap(_ol(_gloss_ul("cat"), _gloss_ul("tomcat", "puss")))
    ]


def test_default_format_is_expanded():
    assert _run({}) == _run({"format": FORMAT_EXPANDED})


def test_include_pos_renders_coloured_chips():
    out = _run({"format": FORMAT_COMPRESSED, "include_pos": True})
    assert out == [_wrap(_ol(_chip("noun") + "cat", _chip("noun") + "tomcat | puss"))]
    # The chip carries a self-contained background colour (no card CSS needed).
    assert "background:#565656" in out[0]


def test_include_examples_renders_accented_box_with_dimmed_english():
    out = _run({"format": FORMAT_COMPRESSED, "include_examples": True})[0]
    box = (
        f'<div style="{_EXAMPLE_BOX_STYLE}"><div lang="ja">猫がいる</div>'
        f'<div style="{_EXAMPLE_EN_STYLE}">there is a cat</div></div>'
    )
    assert out == _wrap(_ol("cat" + box, "tomcat | puss"))
    assert "opacity:.6" in out  # English translation is dimmed


def test_example_without_english_omits_the_dimmed_line():
    result = {
        "results": [
            {
                "lemma": "猫",
                "all_readings": [],
                "entries": [
                    {"senses": [{"pos": [], "glosses": ["cat"], "examples": [{"ja": "猫だ"}]}]}
                ],
            }
        ]
    }
    out = _run({"include_examples": True}, result)[0]
    assert '<div lang="ja">猫だ</div>' in out
    assert _EXAMPLE_EN_STYLE not in out  # no English -> no dimmed line


def test_example_segments_render_ruby_and_highlight_keyword():
    # Segments carry furigana (reading) + the source keyword flag; the keyword run
    # gets ruby *and* the highlight span, plain runs pass through untouched.
    result = {
        "results": [
            {
                "lemma": "猫",
                "all_readings": [],
                "entries": [
                    {
                        "senses": [
                            {
                                "pos": [],
                                "glosses": ["cat"],
                                "examples": [
                                    {
                                        "ja": "彼の猫",
                                        "en": "his cat",
                                        "segments": [
                                            {"text": "彼", "reading": "かれ", "keyword": False},
                                            {"text": "の", "reading": "", "keyword": False},
                                            {"text": "猫", "reading": "ねこ", "keyword": True},
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }
    out = _run({"include_examples": True}, result)[0]
    expected = (
        '<div lang="ja"><ruby>彼<rt>かれ</rt></ruby>の'
        f'<span style="{_HIGHLIGHT_STYLE}"><ruby>猫<rt>ねこ</rt></ruby></span></div>'
    )
    assert expected in out
    assert "彼の猫" not in out  # rendered from segments, not the plain `ja` fallback
    # Keyword is bold + accent-coloured text, not a background highlighter block.
    assert "font-weight:bold" in _HIGHLIGHT_STYLE and "background" not in _HIGHLIGHT_STYLE


def test_example_falls_back_to_plain_ja_without_segments():
    # No segments (older cache / no source ruby) -> plain `ja`, no ruby/highlight.
    result = {
        "results": [
            {
                "lemma": "猫",
                "all_readings": [],
                "entries": [
                    {"senses": [{"pos": [], "glosses": ["cat"], "examples": [{"ja": "猫だ"}]}]}
                ],
            }
        ]
    }
    out = _run({"include_examples": True}, result)[0]
    assert '<div lang="ja">猫だ</div>' in out
    assert "<ruby>" not in out and _HIGHLIGHT_STYLE not in out


def test_readings_trail_is_labelled_chip_row():
    foot = _readings("ねこ", "びょう")
    assert _run({"format": FORMAT_COMPRESSED, "include_readings": True}) == [
        _wrap(_ol("cat", "tomcat | puss") + foot)
    ]
    # Accent-tinted chip, colour-coded apart from the grey POS chip (no bare border line).
    out = _run({"format": FORMAT_COMPRESSED, "include_readings": True})[0]
    assert "Readings" in out and "border-top" not in out


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
    assert _run({"format": FORMAT_COMPRESSED}, _SINGLE) == [_wrap(_ol("cat"))]


def test_single_sense_expanded_still_in_ol():
    assert _run({"format": FORMAT_EXPANDED}, _SINGLE) == [_wrap(_ol(_gloss_ul("cat")))]


def test_single_sense_keeps_pos_and_readings():
    foot = _readings("ねこ")
    assert _run({"include_pos": True, "include_readings": True}, _SINGLE) == [
        _wrap(_ol(_chip("noun") + _gloss_ul("cat")) + foot)
    ]


def test_no_senses_leaves_field_unchanged():
    result = {"results": [{"all_readings": [], "entries": [{"senses": []}]}]}
    assert _run({"format": FORMAT_COMPRESSED}, result) == [None]


def test_dictionary_text_is_html_escaped():
    # Real jitendex glosses contain raw markup characters ("less-than mark (<)");
    # they must land in the field as entities, not as broken HTML.
    result = {
        "results": [
            {
                "lemma": "小なり",
                "all_readings": ["a<b"],
                "entries": [
                    {
                        "senses": [
                            {
                                "pos": ["<noun>"],
                                "glosses": ["less-than mark (<)", "S&M"],
                                "examples": [{"ja": "1 < 2", "en": "one < two"}],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    out = _run(
        {
            "format": FORMAT_COMPRESSED,
            "include_pos": True,
            "include_examples": True,
            "include_readings": True,
        },
        result,
    )[0]
    assert "less-than mark (&lt;)" in out
    assert "S&amp;M" in out
    assert _chip("&lt;noun&gt;") in out
    assert "1 &lt; 2" in out
    assert "one &lt; two" in out
    assert "a&lt;b" in out


def test_example_segment_text_is_html_escaped():
    result = {
        "results": [
            {
                "lemma": "例",
                "all_readings": [],
                "entries": [
                    {
                        "senses": [
                            {
                                "pos": [],
                                "glosses": ["example"],
                                "examples": [
                                    {
                                        "ja": "a<b",
                                        "en": "",
                                        "segments": [
                                            {"text": "a<b", "reading": "<r>", "keyword": False}
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    out = _run({"include_examples": True}, result)[0]
    assert "<ruby>a&lt;b<rt>&lt;r&gt;</rt></ruby>" in out


def test_both_word_and_reading_are_required():
    op = WordDefinitionOperation()
    assert op.applicable({"word": "猫", "word-reading": "ねこ"})
    assert not op.applicable({"word": "猫", "word-reading": ""})  # reading required
    assert not op.applicable({"word": "", "word-reading": "ねこ"})
