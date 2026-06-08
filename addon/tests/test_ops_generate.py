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


def _client(content_results, matched):
    return _FakeClient(
        {
            "/v1/text/content-words": {"results": content_results},
            "/v1/vocab/filter-by-status": {"matched": matched},
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
        GenerationResult(note_id=1, op=plans[0].op, words=[{"lemma": "猫", "reading": "ねこ"}])
    ]


def test_plan_generation_skips_sources_missing_the_sentence():
    client = _client([], [])
    notes = [NoteFields(note_id=1, fields={})]  # no `sentence` -> not applicable
    configured = [ConfiguredOp(GenerateVocabOperation(), {})]
    assert plan_generation(client, configured, notes) == []
    assert client.calls == []  # nothing applicable -> no backend call
