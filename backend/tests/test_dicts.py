import sqlite3
from pathlib import Path

from app.dicts import DictCache
from app.dicts.parsers import (
    parse_jitendex,
    parse_jmdict_furigana,
    parse_jpdb_freq,
    parse_pitch,
)
from app.dicts.paths import (
    DictKind,
    download_target,
    resolve_dict_path,
    shared_dict_dir,
)

# ── Path resolution ──────────────────────────────────────────────────────────


def test_resolve_prefers_env_var(synthetic_dicts: Path) -> None:
    resolved = resolve_dict_path(DictKind.JITENDEX)
    assert resolved == synthetic_dicts / "jitendex.zip"


def test_resolve_returns_none_when_absent(monkeypatch) -> None:
    monkeypatch.setenv("JITENDEX_PATH", "/nope/missing.zip")
    monkeypatch.setattr("app.dicts.paths.shared_dict_dir", lambda: Path("/nope"))
    monkeypatch.setattr("app.dicts.paths._LOCAL_DICT_DIR", Path("/nope"))
    assert resolve_dict_path(DictKind.JITENDEX) is None


def test_download_target_uses_shared_dir_without_env(monkeypatch) -> None:
    monkeypatch.delenv("JPDB_FREQ_PATH", raising=False)
    assert download_target(DictKind.JPDB_FREQ) == shared_dict_dir() / "jpdb-freq-list.zip"


def test_pitch_download_target_uses_env_var(monkeypatch, tmp_path: Path) -> None:
    dest = tmp_path / "pitch.zip"
    monkeypatch.setenv("KANJIUM_PITCH_PATH", str(dest))
    assert download_target(DictKind.PITCH) == dest


def test_pitch_download_target_uses_shared_dir_without_env(monkeypatch) -> None:
    monkeypatch.delenv("KANJIUM_PITCH_PATH", raising=False)
    assert download_target(DictKind.PITCH) == shared_dict_dir() / "kanjium-pitch-accents.zip"


# ── Parsers ──────────────────────────────────────────────────────────────────


def test_parse_jitendex_extracts_senses(synthetic_dicts: Path) -> None:
    rows = {r.lemma: r for r in parse_jitendex(synthetic_dicts / "jitendex.zip")}

    assert rows["食べる"].reading == "たべる"
    assert rows["食べる"].jlpt == 5
    senses = rows["食べる"].senses
    # two senses, sharing the group's POS; every phrasing of each sense kept.
    assert [s["glosses"] for s in senses] == [["to eat"], ["to live on", "to subsist"]]
    assert all(s["pos"] == ["1-dan", "transitive"] for s in senses)
    # example on sense 1: plain `ja` keeps ruby stripped; `segments` preserve the
    # source furigana + the example-keyword highlight (食べる) as kw=True.
    assert senses[0]["examples"] == [
        {
            "ja": "寿司を食べる",
            "en": "to eat sushi",
            "segments": [
                {"text": "寿司", "reading": "すし", "kw": False},
                {"text": "を", "reading": "", "kw": False},
                {"text": "食", "reading": "た", "kw": True},
                {"text": "べる", "reading": "", "kw": True},
            ],
        }
    ]
    assert senses[1]["examples"] == []
    # plain-string glossary falls back to one POS-less, example-less sense.
    assert rows["水"].senses == [{"pos": [], "glosses": ["water"], "examples": []}]


def test_parse_jitendex_drops_low_score_entries(synthetic_dicts: Path) -> None:
    pairs = {(r.lemma, r.reading) for r in parse_jitendex(synthetic_dicts / "jitendex.zip")}
    assert ("人", "ひと") in pairs  # score 200 kept
    assert ("人", "じん") not in pairs  # score 0 dropped: ひと is a >=MIN_SCORE alternate
    assert ("人", "にん") not in pairs  # score -1 always dropped
    assert ("水", "みず") in pairs  # sole score-0 entry kept (no better alternate)


def test_parse_jpdb_freq_marks_kana_form(synthetic_dicts: Path) -> None:
    rows = list(parse_jpdb_freq(synthetic_dicts / "jpdb-freq-list.zip"))
    # kana-form rows: the bare みず entry and the ㋕-marked 水/みず kana spelling.
    kana = [r for r in rows if r.is_kana_form]
    assert {(r.term, r.reading) for r in kana} == {("みず", "みず"), ("水", "みず")}
    # kanji rows carry their own reading, threaded through from the JPDB entry.
    kanji = {(r.term, r.reading): r.rank for r in rows if not r.is_kana_form}
    assert kanji == {("水", "みず"): 500, ("水", "すい"): 800, ("食べる", "たべる"): 700}


def test_parse_furigana_keeps_full_segmentation(synthetic_dicts: Path) -> None:
    rows = {r.text: r for r in parse_jmdict_furigana(synthetic_dicts / "jmdict-furigana.json.zip")}
    # kana chunk kept with rt="" so the whole word can be rebuilt
    assert rows["食べる"].segments == [{"ruby": "食", "rt": "た"}, {"ruby": "べる", "rt": ""}]


def test_parse_pitch_yields_one_row_per_position(synthetic_dicts: Path) -> None:
    rows = list(parse_pitch(synthetic_dicts / "kanjium-pitch-accents.zip"))
    # katakana readings normalized to hiragana; the non-pitch freq row is skipped;
    # a word with two accents yields two rows.
    assert {(r.term, r.reading, r.position) for r in rows} == {
        ("水", "みず", 0),
        ("人", "ひと", 0),
        ("人", "ひと", 2),
        ("人", "にん", 1),
        ("食べる", "たべる", 2),
    }


# ── Cache build + lookups ────────────────────────────────────────────────────


def test_build_cache_reports_entries(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert cache is not None
    status = {s.name: s for s in cache.status()}
    assert status["meanings"].entries == 3  # 食べる, 水, 人/ひと (low-score readings dropped)
    assert status["frequencies"].entries == 4  # (水,みず), (水,すい), (みず,みず), (食べる,たべる)
    assert status["furigana"].entries == 6  # 食べる, 水, 日本語, 人/ひと, 人/じん, 十分
    assert status["pitches"].entries == 5  # 水/みず, 人/ひと x2, 人/にん, 食べる/たべる
    assert all(s.loaded for s in status.values())


def test_status_counts_are_computed_once(built_cache: Path) -> None:
    """A built cache is immutable, so /health must not re-scan it on every call."""
    cache = DictCache.open(built_cache)
    assert cache is not None
    first = cache.status()

    scans: list[str] = []
    real_conn = cache._conn

    def counting_conn():
        scans.append("scan")
        return real_conn()

    cache._conn = counting_conn  # type: ignore[method-assign]
    assert cache.status() == first  # same answer...
    assert not scans  # ...served from the memo, without touching the db again


def test_lookup_meaning(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert cache is not None
    entries = cache.lookup_meaning("食べる")
    assert [s["glosses"] for s in entries[0]["senses"]] == [
        ["to eat"],
        ["to live on", "to subsist"],
    ]
    assert entries[0]["reading"] == "たべる"
    assert cache.lookup_meaning("食べる", reading="ちがう") == []


def test_lookup_frequency_prefers_kanji_rank(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert cache is not None
    # No reading -> best (lowest) rank across the term's readings; kanji 500 wins
    # over the ㋕ kana-spelling 2100 for 水/みず.
    assert cache.lookup_frequency("水") == 500
    assert cache.lookup_frequency("みず") == 1500
    assert cache.lookup_frequency("存在しない") is None


def test_lookup_spelling_ranks_keeps_both_figures(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert cache is not None
    # Both figures survive the build, so a caller can compare them: 水 is ranked
    # as written and again through its kana spelling; みず has only the kana
    # figure, 食べる only the as-written one.
    assert cache.lookup_spelling_ranks("水") == (500, 2100)
    assert cache.lookup_spelling_ranks("みず") == (None, 1500)
    assert cache.lookup_spelling_ranks("食べる") == (700, None)
    assert cache.lookup_spelling_ranks("存在しない") == (None, None)


def test_lookup_frequency_disambiguates_by_reading(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert cache is not None
    # Same term, different readings -> different ranks (per-(term, reading) key).
    assert cache.lookup_frequency("水", "みず") == 500
    assert cache.lookup_frequency("水", "すい") == 800
    # Katakana reading is normalized to hiragana before matching.
    assert cache.lookup_frequency("水", "ミズ") == 500
    # Unranked term + a reading that is itself a kana entry -> kana-form fallback.
    assert cache.lookup_frequency("淼", "みず") == 1500
    # Reading matches no (term, reading) and isn't a kana entry -> None.
    assert cache.lookup_frequency("水", "ちがう") is None


def test_lookup_frequency_many_matches_the_single_lookup(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert cache is not None
    terms = ["水", "みず", "存在しない", "水"]  # includes a dup and an unranked term
    ranks = cache.lookup_frequency_many(terms)
    # Same answers as the one-at-a-time path; unranked terms are simply absent.
    assert ranks == {"水": 500, "みず": 1500}
    assert all(ranks.get(t) == cache.lookup_frequency(t) for t in terms)
    assert cache.lookup_frequency_many([]) == {}


def test_lookup_frequency_many_chunks_past_the_variable_limit(
    built_cache: Path, monkeypatch
) -> None:
    """SQLite caps a statement at 999 variables; a full-deck sort passes thousands."""
    cache = DictCache.open(built_cache)
    assert cache is not None
    monkeypatch.setattr("app.dicts.cache._CHUNK", 2)
    terms = [f"未知{i}" for i in range(7)] + ["水"]
    assert cache.lookup_frequency_many(terms) == {"水": 500}


def test_lookup_furigana(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert cache is not None
    assert cache.lookup_furigana("水", "みず") == [{"ruby": "水", "rt": "みず"}]
    assert cache.lookup_furigana("水", "wrong") is None


def test_lookup_pitch(built_cache: Path) -> None:
    cache = DictCache.open(built_cache)
    assert cache is not None
    # Single accent; katakana reading is normalized to hiragana before matching.
    assert cache.lookup_pitch("水", "みず") == [0]
    assert cache.lookup_pitch("水", "ミズ") == [0]
    # A reading with two accepted accents -> both, ascending.
    assert cache.lookup_pitch("人", "ひと") == [0, 2]
    # No reading -> union across the term's readings (ひと 0,2 + にん 1).
    assert cache.lookup_pitch("人") == [0, 1, 2]
    # Unknown term or wrong reading -> empty.
    assert cache.lookup_pitch("存在しない") == []
    assert cache.lookup_pitch("水", "ちがう") == []


def test_open_returns_none_when_cache_missing(tmp_path: Path) -> None:
    assert DictCache.open(tmp_path / "absent.db") is None


def test_open_returns_none_on_schema_version_mismatch(built_cache: Path) -> None:
    conn = sqlite3.connect(built_cache)
    conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    assert DictCache.open(built_cache) is None


def test_open_returns_none_on_unreadable_cache_file(tmp_path: Path) -> None:
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"not a sqlite database")
    assert DictCache.open(garbage) is None


def test_lookups_are_memoized(built_cache: Path) -> None:
    """A built cache is immutable, and the same words recur constantly per deck."""
    cache = DictCache.open(built_cache)
    assert cache is not None

    first = cache.lookup_frequency("水", "みず")
    assert cache.lookup_frequency("水", "みず") == first
    assert cache._lookup_frequency.cache_info().hits == 1

    cache.lookup_furigana("水", "みず")
    cache.lookup_furigana("水", "みず")
    assert cache._lookup_furigana.cache_info().hits == 1

    cache.close()
    assert cache._lookup_frequency.cache_info().currsize == 0  # cleared on close
