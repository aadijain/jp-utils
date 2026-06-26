import pytest
from fastapi.testclient import TestClient

from app.text.locate import locate
from app.text.tokenizer import Tokenizer


def _segments(result):
    return [(s.text, s.match) for s in result.segments]


def test_locate_plain_match(tokenizer: Tokenizer) -> None:
    result = locate(tokenizer, "猫が好きだ", "猫")
    assert _segments(result) == [("猫", True), ("が好きだ", False)]


def test_locate_is_inflection_aware(tokenizer: Tokenizer) -> None:
    # 食べた is an inflection of 食べる; matched by lemma, not literal substring.
    result = locate(tokenizer, "りんごを食べた", "食べる")
    matched = [s.text for s in result.segments if s.match]
    assert matched == ["食べた"]


def test_locate_absorbs_conjugation_suffixes(tokenizer: Tokenizer) -> None:
    # 食べている = 食べ + て + いる across three tokens; the whole surface is one match.
    result = locate(tokenizer, "ご飯を食べている", "食べる")
    matched = [s.text for s in result.segments if s.match]
    assert matched == ["食べている"]


@pytest.mark.parametrize(
    ("text", "word", "expected"),
    [
        # A word Sudachi splits in isolation is still found whole in a sentence.
        ("お茶を飲む", "お茶", "お茶"),
        ("記憶喪失になった", "記憶喪失", "記憶喪失"),
        # ...and is matched through its own conjugation.
        ("足元をすくわれた", "足元をすくう", "足元をすくわれた"),
        # The reverse case: split alone, kept as one morpheme in context.
        ("対等な立場ですよ", "対等", "対等な"),
    ],
)
def test_locate_finds_a_multi_morpheme_word(
    tokenizer: Tokenizer, text: str, word: str, expected: str
) -> None:
    result = locate(tokenizer, text, word)
    assert [s.text for s in result.segments if s.match] == [expected]


@pytest.mark.parametrize(
    ("text", "word", "expected"),
    [
        # から / けど attach to a finished clause - they are not the word's tail.
        ("残念だね〜惜しかったけど", "惜しい", "惜しかった"),
        ("内臓が傷ついてるから", "傷つく", "傷ついてる"),
        # A copula is not part of a plain noun.
        ("俺は新人だ", "新人", "新人"),
        ("働くのが道理でしょ", "道理", "道理"),
        # 行く / ある are tagged 非自立可能 by possibility, not by use.
        ("熱っぽくて保健室行くところ", "保健室", "保健室"),
        # A na-adjective does inflect through the copula, so that one is kept.
        ("広大な大陸の中心", "広大", "広大な"),
        # As does a サ変 noun through its light verb.
        ("こいつらを攻略していた", "攻略", "攻略していた"),
    ],
)
def test_locate_stops_where_the_word_ends(
    tokenizer: Tokenizer, text: str, word: str, expected: str
) -> None:
    result = locate(tokenizer, text, word)
    assert [s.text for s in result.segments if s.match] == [expected]


def test_locate_match_in_middle(tokenizer: Tokenizer) -> None:
    result = locate(tokenizer, "私は猫が好き", "猫")
    assert _segments(result) == [("私は", False), ("猫", True), ("が好き", False)]


def test_locate_no_match_returns_whole_text(tokenizer: Tokenizer) -> None:
    result = locate(tokenizer, "猫が好き", "犬")
    assert _segments(result) == [("猫が好き", False)]


def test_locate_empty_inputs(tokenizer: Tokenizer) -> None:
    assert locate(tokenizer, "", "猫").segments == []
    assert _segments(locate(tokenizer, "猫", "")) == [("猫", False)]


def test_locate_endpoint(text_client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = text_client.post(
        "/v1/text/locate",
        headers=auth_headers,
        json={
            "queries": [
                {"text": "りんごを食べた", "word": "食べる"},
                {"text": "猫が好き", "word": "犬"},
            ]
        },
    )

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert [(s["text"], s["match"]) for s in results[0]["segments"]] == [
        ("りんごを", False),
        ("食べた", True),
    ]
    # No match -> the whole text comes back as one unmatched segment.
    assert results[1]["segments"] == [{"text": "猫が好き", "match": False}]


def test_locate_unavailable_without_tokenizer(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/v1/text/locate", headers=auth_headers, json={"queries": [{"text": "猫", "word": "猫"}]}
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tokenizer_unavailable"


def test_locate_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/text/locate", json={"queries": [{"text": "猫", "word": "猫"}]})
    assert resp.status_code == 401
