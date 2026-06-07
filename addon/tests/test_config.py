"""Tests for the add-on config schema (pure; no Anki)."""

from jp_utils.config import AddonConfig, Pipeline, PipelineStep


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


def test_normalize_steps_drops_junk_and_defaults_only_if_empty() -> None:
    cfg = AddonConfig.from_dict(
        {"pipelines": [{"note_type": "N", "steps": [{"no_op": 1}, {"op": "definition"}]}]}
    )
    steps = cfg.pipelines[0].steps
    assert [s.op for s in steps] == ["definition"]  # junk dropped
    assert steps[0].only_if_empty is True  # conservative default


def test_present_pipelines_are_used() -> None:
    cfg = AddonConfig.from_dict({"pipelines": []})  # explicit empty list -> no pipelines
    assert cfg.pipelines == []
