"""Tests for the clear-formatting operation (local HTML strip of the sentence field)."""

from jp_utils.ops import ConfiguredOp, NoteFields, plan_operations
from jp_utils.ops.clear_formatting import ClearFormattingOperation, strip_formatting


def test_strip_drops_tags_and_unescapes():
    assert strip_formatting("<b>hi</b> &amp; bye") == "hi & bye"


def test_strip_converts_br_to_newline():
    assert strip_formatting("a<br>b<br/>c<BR />d") == "a\nb\nc\nd"


def test_strip_preserves_anki_text_ruby():
    # Text-form ruby has no tags, so it passes through untouched.
    assert strip_formatting(" 漢字[かんじ]を見る") == " 漢字[かんじ]を見る"


def test_strip_folds_html_ruby_to_text_form():
    assert strip_formatting("<ruby>漢字<rt>かんじ</rt></ruby>") == "漢字[かんじ]"
    # <rp> fallback parens are dropped, reading kept.
    assert strip_formatting("<ruby>字<rp>(</rp><rt>じ</rt><rp>)</rp></ruby>") == "字[じ]"


def test_strip_does_not_collapse_whitespace():
    assert strip_formatting("a   b\n c") == "a   b\n c"


def test_strip_keeps_literal_escaped_brackets():
    # Escaped angle brackets are literal text, not a tag to strip.
    assert strip_formatting("use &lt;br&gt; here") == "use <br> here"


def test_compute_strips_sentence_else_none():
    op = ClearFormattingOperation()
    sources = [{"sentence": "<i>x</i>"}, {"sentence": "clean"}]
    # Only the field whose value changes is rewritten; an already-clean field -> None.
    assert op.compute(None, sources) == ["x", None]


def test_plan_operations_writes_stripped_sentence():
    op = ClearFormattingOperation()
    notes = [NoteFields(note_id=1, fields={"sentence": "<b>foo</b>"})]
    plans = plan_operations(None, [ConfiguredOp(op)], notes)
    assert len(plans) == 1
    [update] = plans[0].updates
    assert update.alias == "sentence"
    assert update.value == "foo"


def test_plan_operations_idempotent_when_already_clean():
    op = ClearFormattingOperation()
    notes = [NoteFields(note_id=1, fields={"sentence": "already plain"})]
    assert plan_operations(None, [ConfiguredOp(op)], notes) == []


def test_target_param_strips_a_different_alias_in_place():
    op = ClearFormattingOperation()
    # The target defaults to `sentence`; point it at `word-meaning` instead.
    assert op.io_spec({"target": "word-meaning"}).outputs == ("word-meaning",)
    notes = [NoteFields(note_id=1, fields={"sentence": "<b>keep</b>", "word-meaning": "<i>x</i>"})]
    plans = plan_operations(None, [ConfiguredOp(op, {"target": "word-meaning"})], notes)
    [update] = plans[0].updates
    assert update.alias == "word-meaning"  # the chosen field is cleaned, in place
    assert update.value == "x"
