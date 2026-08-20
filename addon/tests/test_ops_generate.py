"""Tests for the generate-vocab operation (compose path: content-words + filter)."""

from jp_utils.ops import ConfiguredOp, GenerationResult, NoteFields, plan_generation
from jp_utils.ops.generate import GenerateVocabOperation


class _FakeClient:
    """Returns a canned response per path; records the bodies it was sent."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls = []

    def post(self, path, body):
        self.calls.append((path, body))
        return self.responses[path]


def _client(content_results, matched, frequencies=None):
    return _FakeClient(
        {
            "/v1/text/content-words": {"results": content_results},
            "/v1/vocab/filter-by-status": {"matched": matched},
            "/v1/text/frequency": {"results": frequencies or []},
        }
    )


def test_keeps_only_new_words_and_strips_markup():
    # Sentence has two content words; only 猫 is still new (status filter keeps it).
    client = _client(
        [[{"lemma": "猫", "reading": "ねこ"}, {"lemma": "好き", "reading": "すき"}]],
        [{"lemma": "猫", "reading": "ねこ"}],
    )
    out = GenerateVocabOperation().generate(client, [{"sentence": "<b>猫</b>が好き"}])

    assert out == [[{"lemma": "猫", "reading": "ねこ"}]]
    content_call, filter_call = client.calls
    assert content_call == ("/v1/text/content-words", {"texts": ["猫が好き"]})
    # The filter is asked lemma-only over {unknown, seen} for every candidate.
    assert filter_call[0] == "/v1/vocab/filter-by-status"
    assert filter_call[1]["statuses"] == ["unknown", "seen"]
    assert filter_call[1]["match_lemma_only"] is True


def test_filters_in_one_batched_call_across_sentences():
    client = _client(
        [[{"lemma": "猫", "reading": "ねこ"}], [{"lemma": "犬", "reading": "いぬ"}]],
        [{"lemma": "犬", "reading": "いぬ"}],  # only 犬 survives
    )
    out = GenerateVocabOperation().generate(client, [{"sentence": "猫だ"}, {"sentence": "犬だ"}])
    assert out == [[], [{"lemma": "犬", "reading": "いぬ"}]]
    # Exactly two calls: one content-words, one filter (not one filter per source).
    assert [c[0] for c in client.calls] == [
        "/v1/text/content-words",
        "/v1/vocab/filter-by-status",
    ]


def test_no_candidates_skips_the_filter_call():
    client = _client([[]], [])
    out = GenerateVocabOperation().generate(client, [{"sentence": "。。。"}])
    assert out == [[]]
    assert [c[0] for c in client.calls] == ["/v1/text/content-words"]  # no filter call


def test_plan_generation_emits_one_result_per_source_with_words():
    client = _client(
        [[{"lemma": "猫", "reading": "ねこ"}], []],
        [{"lemma": "猫", "reading": "ねこ"}],
    )
    notes = [
        NoteFields(note_id=1, fields={"sentence": "猫だ"}),
        NoteFields(note_id=2, fields={"sentence": "．"}),
    ]
    configured = [ConfiguredOp(GenerateVocabOperation(), {"target_deck": "Words"})]

    plans = plan_generation(client, configured, notes)

    assert plans == [
        GenerationResult(
            note_id=1,
            op=plans[0].op,
            params={"target_deck": "Words"},
            words=[{"lemma": "猫", "reading": "ねこ"}],
        )
    ]


def test_plan_generation_skips_sources_missing_the_sentence():
    client = _client([], [])
    notes = [NoteFields(note_id=1, fields={})]  # no `sentence` -> not applicable
    configured = [ConfiguredOp(GenerateVocabOperation(), {})]
    assert plan_generation(client, configured, notes) == []
    assert client.calls == []  # nothing applicable -> no backend call


def test_drops_kana_only_words_more_frequent_than_the_floor():
    # やたら is above the floor and kept; ばかり is below it and skipped.
    client = _client(
        [[{"lemma": "やたら", "reading": "ヤタラ"}, {"lemma": "ばかり", "reading": "バカリ"}]],
        [{"lemma": "やたら", "reading": "ヤタラ"}, {"lemma": "ばかり", "reading": "バカリ"}],
        frequencies=[{"rank": 2270}, {"rank": 296}],
    )
    out = GenerateVocabOperation().generate(client, [{"sentence": "やたらばかり"}])

    assert out == [[{"lemma": "やたら", "reading": "ヤタラ"}]]
    freq_call = client.calls[-1]
    assert freq_call == (
        "/v1/text/frequency",
        {
            "queries": [
                {"term": "やたら", "reading": "ヤタラ"},
                {"term": "ばかり", "reading": "バカリ"},
            ]
        },
    )


def test_kana_filter_keeps_unranked_words_and_ignores_kanji_words():
    client = _client(
        [[{"lemma": "猫", "reading": "ネコ"}, {"lemma": "くすぐる", "reading": "クスグル"}]],
        [{"lemma": "猫", "reading": "ネコ"}, {"lemma": "くすぐる", "reading": "クスグル"}],
        frequencies=[{"rank": None}],  # only the kana word is looked up
    )
    out = GenerateVocabOperation().generate(client, [{"sentence": "猫をくすぐる"}])

    assert out == [
        [{"lemma": "猫", "reading": "ネコ"}, {"lemma": "くすぐる", "reading": "クスグル"}]
    ]
    assert client.calls[-1][1] == {"queries": [{"term": "くすぐる", "reading": "クスグル"}]}


def test_kana_floor_is_a_param_and_zero_disables_the_lookup():
    words = [[{"lemma": "ばかり", "reading": "バカリ"}]]
    matched = [{"lemma": "ばかり", "reading": "バカリ"}]

    # A lower floor keeps a word the default (2000) would have dropped.
    client = _client(words, matched, frequencies=[{"rank": 296}])
    out = GenerateVocabOperation().generate(
        client, [{"sentence": "ばかり"}], {"min_kana_rank": "100"}
    )
    assert out == [matched]

    # 0 turns the filter off entirely - no frequency call at all.
    client = _client(words, matched, frequencies=[{"rank": 296}])
    out = GenerateVocabOperation().generate(
        client, [{"sentence": "ばかり"}], {"min_kana_rank": "0"}
    )
    assert out == [matched]
    assert [c[0] for c in client.calls] == [
        "/v1/text/content-words",
        "/v1/vocab/filter-by-status",
    ]


def test_blank_or_junk_floor_falls_back_to_the_default():
    for value in ("", "   ", "not-a-number"):
        client = _client(
            [[{"lemma": "ばかり", "reading": "バカリ"}]],
            [{"lemma": "ばかり", "reading": "バカリ"}],
            frequencies=[{"rank": 296}],
        )
        out = GenerateVocabOperation().generate(
            client, [{"sentence": "ばかり"}], {"min_kana_rank": value}
        )
        assert out == [[]], value


def test_no_kana_survivors_skips_the_frequency_call():
    client = _client(
        [[{"lemma": "猫", "reading": "ネコ"}]],
        [{"lemma": "猫", "reading": "ネコ"}],
    )
    GenerateVocabOperation().generate(client, [{"sentence": "猫だ"}])
    assert [c[0] for c in client.calls] == [
        "/v1/text/content-words",
        "/v1/vocab/filter-by-status",
    ]
