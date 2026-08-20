import pytest
from fastapi.testclient import TestClient

from app.text.normalize import deinflected_key, normalize
from app.text.tokenizer import Tokenizer


def test_normalize_deinflects_verb(tokenizer: Tokenizer) -> None:
    result = normalize(tokenizer, "食べた")
    assert result.lemma == "食べる"
    assert result.reading == "たべる"  # lemma reading, in hiragana


def test_normalize_uses_normalized_form_field(tokenizer: Tokenizer) -> None:
    result = normalize(tokenizer, "した")
    assert result.lemma == "する"  # dictionary form (matches dict headwords)
    assert result.normalized == "為る"  # Sudachi's variant-unified form
    assert result.reading == "する"


def test_normalize_plain_noun(tokenizer: Tokenizer) -> None:
    result = normalize(tokenizer, "猫")
    assert (result.lemma, result.reading) == ("猫", "ねこ")


@pytest.mark.parametrize(
    ("surface", "lemma", "reading"),
    [
        ("記憶喪失", "記憶喪失", "きおくそうしつ"),  # compound noun
        ("上等", "上等", "じょうとう"),  # noun + 接尾辞
        ("お茶", "お茶", "おちゃ"),  # 接頭辞 + noun
        ("足元をすくう", "足元をすくう", "あしもとをすくう"),  # phrasal entry
        ("次第に", "次第に", "しだいに"),  # the trailing particle is part of the word
    ],
)
def test_normalize_keeps_a_split_surface_whole(
    tokenizer: Tokenizer, surface: str, lemma: str, reading: str
) -> None:
    # Sudachi splits each of these, and taking only the head morpheme would hand
    # back a fragment (記憶 / 上 / お) that looks just like a clean reduction.
    result = normalize(tokenizer, surface)
    assert (result.lemma, result.reading) == (lemma, reading)
    assert result.covered


def test_normalize_still_deinflects_a_split_surface(tokenizer: Tokenizer) -> None:
    # Only the span's last morpheme conjugates, so folding the rest in does not
    # cost the deinflection.
    assert normalize(tokenizer, "放っておく").lemma == "放る"


@pytest.mark.parametrize("surface", ["。", "ました", "だます"])
def test_normalize_reports_a_surface_with_no_word_head(tokenizer: Tokenizer, surface: str) -> None:
    # Punctuation, a bare auxiliary, and a misparse (だます -> copula だ + ます)
    # all yield a key that is a guess. Consumers writing durable state skip it.
    assert not normalize(tokenizer, surface).covered


def test_normalize_marks_an_ordinary_word_covered(tokenizer: Tokenizer) -> None:
    assert normalize(tokenizer, "食べさせられた").covered


def test_normalize_empty(tokenizer: Tokenizer) -> None:
    result = normalize(tokenizer, "   ")
    assert result.lemma == ""
    assert result.reading == ""
    assert not result.covered


def test_deinflected_key_is_the_retry_key_for_an_inflected_surface(
    tokenizer: Tokenizer,
) -> None:
    # The reading comes from the same analysis as the lemma: せめ describes 攻め,
    # which the lemma no longer is.
    assert deinflected_key(tokenizer, "食べた") == ("食べる", "たべる")
    assert deinflected_key(tokenizer, "攻め") == ("攻める", "せめる")


def test_deinflected_key_is_none_when_there_is_nothing_new_to_try(tokenizer: Tokenizer) -> None:
    assert deinflected_key(tokenizer, "猫") is None  # already its own lemma
    assert deinflected_key(tokenizer, " 猫 ") is None  # ...whitespace and all
    assert deinflected_key(tokenizer, "上等") is None  # a compound is folded, not truncated
    assert deinflected_key(tokenizer, "。") is None  # no word head at all
    assert deinflected_key(tokenizer, "だます") is None  # a misparse is not a retry key
    assert deinflected_key(tokenizer, "   ") is None


def test_normalize_endpoint(text_client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = text_client.post(
        "/v1/text/normalize",
        headers=auth_headers,
        json={"surfaces": ["行きました", "猫"]},
    )

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert (results[0]["lemma"], results[0]["reading"]) == ("行く", "いく")
    assert results[1]["lemma"] == "猫"


def test_normalize_unavailable_without_tokenizer(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post("/v1/text/normalize", headers=auth_headers, json={"surfaces": ["猫"]})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tokenizer_unavailable"


def test_normalize_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/text/normalize", json={"surfaces": ["猫"]})
    assert resp.status_code == 401
