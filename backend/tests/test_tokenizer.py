from app.text.tokenizer import Tokenizer
from shared.text import SplitMode


def test_tokenizer_emits_dictionary_forms(tokenizer: Tokenizer) -> None:
    tokens = tokenizer.tokenize("日本語を勉強した")
    surfaces = [t.surface for t in tokens]
    assert surfaces == ["日本語", "を", "勉強", "し", "た"]

    shita = next(t for t in tokens if t.surface == "し")
    assert shita.dictionary_form == "する"  # deinflected lemma
    assert shita.reading == "シ"
    assert "動詞" in shita.part_of_speech
    assert "*" not in shita.part_of_speech


def test_tokenizer_empty_string_returns_no_tokens(tokenizer: Tokenizer) -> None:
    assert tokenizer.tokenize("") == []


def test_tokenizer_split_mode_changes_granularity(tokenizer: Tokenizer) -> None:
    # 選挙管理委員会 is one unit in C but splits in A.
    a = tokenizer.tokenize("選挙管理委員会", SplitMode.A)
    c = tokenizer.tokenize("選挙管理委員会", SplitMode.C)
    assert len(a) > len(c)


def test_reading_of_concatenates_morpheme_readings(tokenizer: Tokenizer) -> None:
    assert tokenizer.reading_of("記憶喪失") == "キオクソウシツ"
    assert tokenizer.reading_of("") == ""


def test_reading_of_is_memoized(tokenizer: Tokenizer) -> None:
    # A sweep re-derives the same lemmas' readings over and over (~5x), so the
    # re-tokenization behind them is cached.
    tokenizer.reading_of.cache_clear()
    tokenizer.reading_of("食べる")
    tokenizer.reading_of("食べる")
    info = tokenizer.reading_of.cache_info()
    assert (info.hits, info.misses) == (1, 1)
