"""Tests for the add-on config schema (pure; no Anki)."""

from jp_utils.config import (
    AddonConfig,
    Pipeline,
    PipelineStep,
    find_pipeline,
    pipeline_problems,
    pipelines_for_trigger,
    step_unmapped_aliases,
)


class _Op:
    """Duck-typed stand-in for an Operation (key + aliases) for validator tests."""

    def __init__(self, key, input_aliases, output_alias):
        self.key = key
        self.input_aliases = input_aliases
        self.output_alias = output_alias


_OPS = [_Op("word-reading", ("word",), "word-reading")]
_NOTE_TYPES = {"Lapis": {"word": "Expression", "word-reading": "Reading"}}


def test_defaults_seed_lapis_but_no_pipelines() -> None:
    cfg = AddonConfig()
    assert cfg.server_url == "http://localhost:8000"
    assert cfg.note_types["Lapis"]["definition"] == "MainDefinition"
    assert cfg.pipelines == []  # pipelines are not seeded


def test_from_dict_empty_seeds_lapis_no_pipelines() -> None:
    cfg = AddonConfig.from_dict({})
    assert "Lapis" in cfg.note_types
    assert cfg.pipelines == []


def test_round_trip_to_and_from_dict() -> None:
    cfg = AddonConfig(
        server_url="http://h:9",
        token="t",
        note_types={"N": {"word": "W"}},
        pipelines=[Pipeline(deck="D", note_type="N", steps=[PipelineStep("frequency")])],
    )
    again = AddonConfig.from_dict(cfg.to_dict())
    assert again == cfg


def test_from_dict_flattens_legacy_input_output_maps() -> None:
    # A hand-edited or older config with nested inputs/outputs still loads.
    cfg = AddonConfig.from_dict(
        {
            "note_types": {
                "Lapis": {
                    "inputs": {"word": "Expression", "frequency": "FreqSort"},
                    "outputs": {"frequency": "FreqSort", "definition": "MainDefinition"},
                }
            }
        }
    )
    assert cfg.note_types["Lapis"] == {
        "word": "Expression",
        "frequency": "FreqSort",
        "definition": "MainDefinition",
    }


def test_normalize_pipelines_drops_entries_without_note_type() -> None:
    cfg = AddonConfig.from_dict(
        {"pipelines": [{"deck": "D"}, {"deck": "D", "note_type": "N", "steps": [{"op": "x"}]}]}
    )
    assert [(p.deck, p.note_type) for p in cfg.pipelines] == [("D", "N")]
    assert cfg.pipelines[0].steps[0].op == "x"


def test_normalize_triggers_keeps_known_dedups_drops_junk() -> None:
    cfg = AddonConfig.from_dict(
        {"pipelines": [{"note_type": "N", "auto_triggers": ["bogus", "start", "close", "start"]}]}
    )
    # Only the known `start` survives, deduped; unknown keys (incl. the dropped
    # `close` event) are gone.
    assert cfg.pipelines[0].auto_triggers == ["start"]


def test_auto_triggers_default_empty_and_round_trip() -> None:
    assert Pipeline(deck="D", note_type="N").auto_triggers == []
    cfg = AddonConfig(pipelines=[Pipeline("D", "N", auto_triggers=["start"])])
    assert AddonConfig.from_dict(cfg.to_dict()) == cfg


def test_name_and_comment_default_empty_and_round_trip() -> None:
    p = Pipeline(deck="D", note_type="N")
    assert p.name == "" and p.comment == ""
    cfg = AddonConfig(pipelines=[Pipeline("D", "N", name="My loop", comment="notes\nhere")])
    assert AddonConfig.from_dict(cfg.to_dict()) == cfg


def test_normalize_pipelines_coerces_name_and_comment() -> None:
    cfg = AddonConfig.from_dict({"pipelines": [{"note_type": "N", "name": 5, "comment": None}]})
    p = cfg.pipelines[0]
    assert p.name == "5"  # non-string coerced
    assert p.comment == ""  # None -> empty


def test_pipelines_for_trigger_filters_by_event_enabled_and_target() -> None:
    pipelines = [
        Pipeline("D1", "N", auto_triggers=["start"]),
        Pipeline("D2", "N", enabled=False, auto_triggers=["start"]),  # disabled
        Pipeline("", "N", auto_triggers=["start"]),  # no deck -> not runnable
        Pipeline("D4", "N"),  # no trigger
    ]
    assert [p.deck for p in pipelines_for_trigger(pipelines, "start")] == ["D1"]


def test_normalize_steps_drops_junk_and_keeps_params() -> None:
    cfg = AddonConfig.from_dict(
        {
            "pipelines": [
                {
                    "note_type": "N",
                    "steps": [
                        {"no_op": 1},
                        {"op": "definition", "params": {"only_if_empty": False}},
                    ],
                }
            ]
        }
    )
    steps = cfg.pipelines[0].steps
    assert [s.op for s in steps] == ["definition"]  # junk (no "op") dropped
    assert steps[0].params == {"only_if_empty": False}  # params preserved verbatim


def test_present_pipelines_are_used() -> None:
    cfg = AddonConfig.from_dict({"pipelines": []})  # explicit empty list -> no pipelines
    assert cfg.pipelines == []


def test_find_pipeline_requires_exact_deck_no_blank_fallback() -> None:
    blank = Pipeline(deck="", note_type="Lapis")
    exact = Pipeline(deck="Word", note_type="Lapis")
    pipelines = [blank, exact]
    assert find_pipeline(pipelines, "Word", "Lapis") is exact
    assert find_pipeline(pipelines, "Other", "Lapis") is None  # blank deck is not a fallback


def test_find_pipeline_respects_note_type_and_enabled() -> None:
    disabled = Pipeline(deck="Word", note_type="Lapis", enabled=False)
    assert find_pipeline([disabled], "Word", "Lapis") is None  # disabled -> no match
    other = Pipeline(deck="Word", note_type="Other")
    assert find_pipeline([other], "Word", "Lapis") is None  # note type mismatch


def test_find_pipeline_none_when_no_match() -> None:
    assert find_pipeline([], "Word", "Lapis") is None


def test_pipeline_problems_none_when_valid() -> None:
    p = Pipeline(deck="Word", note_type="Lapis", steps=[PipelineStep("word-reading")])
    assert pipeline_problems(p, [p], _NOTE_TYPES, _OPS) == []


def test_pipeline_problems_flags_missing_deck_and_note_type() -> None:
    p = Pipeline(deck="", note_type="")
    problems = pipeline_problems(p, [p], _NOTE_TYPES, _OPS)
    assert any("deck" in m for m in problems)
    assert any("note type" in m for m in problems)


def test_pipeline_problems_flags_duplicate_target() -> None:
    a = Pipeline(deck="Word", note_type="Lapis")
    b = Pipeline(deck="Word", note_type="Lapis")
    problems = pipeline_problems(a, [a, b], _NOTE_TYPES, _OPS)
    assert any("Another pipeline" in m for m in problems)


def test_pipeline_problems_flags_unmapped_alias() -> None:
    # Note type maps the input but NOT the output alias -> op would no-op silently.
    note_types = {"Lapis": {"word": "Expression"}}
    p = Pipeline(deck="Word", note_type="Lapis", steps=[PipelineStep("word-reading")])
    problems = pipeline_problems(p, [p], note_types, _OPS)
    assert any("word-reading" in m for m in problems)


def test_step_unmapped_aliases_lists_input_and_output() -> None:
    p_step = PipelineStep("word-reading")
    assert step_unmapped_aliases(p_step, {}, "Lapis", _OPS) == ["word", "word-reading"]
    assert step_unmapped_aliases(p_step, _NOTE_TYPES, "Lapis", _OPS) == []
    assert step_unmapped_aliases(PipelineStep("ghost"), {}, "Lapis", _OPS) == []  # unregistered


class _SortOp:
    """Duck-typed sort op: reads an input alias, writes NO output (no output_alias)."""

    def __init__(self, key, input_aliases):
        self.key = key
        self.input_aliases = input_aliases


def test_step_unmapped_aliases_ignores_output_for_ops_without_one() -> None:
    ops = [_SortOp("int-sort", ("frequency",))]
    note_types = {"Lapis": {"frequency": "FreqSort"}}
    step = PipelineStep("int-sort")
    # Input mapped + no output to check -> valid (no false "unmapped output").
    assert step_unmapped_aliases(step, note_types, "Lapis", ops) == []
    # Input unmapped is still reported.
    assert step_unmapped_aliases(step, {}, "Lapis", ops) == ["frequency"]
