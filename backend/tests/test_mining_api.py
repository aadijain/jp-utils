import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dicts import DictCache
from app.main import create_app
from app.vocab import VocabStore
from shared.vocab import RecordEntry


@pytest.fixture
def mining_client(
    settings: Settings, tokenizer, vocab_store: VocabStore, built_cache
) -> TestClient:
    """Client with the tokenizer, vocab store and (synthetic) dict cache wired up."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.tokenizer = tokenizer
    app.state.vocab_store = vocab_store
    app.state.dict_cache = DictCache.open(built_cache)
    return TestClient(app, raise_server_exceptions=False)


def _sort(client: TestClient, headers: dict[str, str], sentences: list[str]) -> list[dict]:
    resp = client.post(
        "/v1/mining/nplus1sort",
        headers=headers,
        json={"sentences": [{"text": s} for s in sentences]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_nplus1_orders_fewest_new_words_first(
    mining_client: TestClient, vocab_store: VocabStore, auth_headers: dict[str, str]
) -> None:
    vocab_store.record([RecordEntry(lemma="食べる", reading="たべる")])  # known
    # s0 unknown {猫,魚}=2, s1 unknown {魚}=1, s2 unknown {犬,猫}=2.
    # greedy: s1 (learn 魚) -> s0 (learn 猫) -> s2. sequence 1,0,2.
    body = _sort(mining_client, auth_headers, ["猫が魚を食べる", "魚を食べる", "犬が猫を食べる"])

    results = body["results"]
    assert [r["sequence"] for r in results] == [1, 0, 2]
    assert [r["unknown_count"] for r in results] == [2, 1, 2]  # vs the known set, not the sim
    lemmas_1 = [w["lemma"] for w in results[1]["words"]]
    assert "魚" in lemmas_1 and "食べる" in lemmas_1
    assert body["version"] == vocab_store.status().version


def test_works_without_dict_cache(
    settings: Settings, tokenizer, vocab_store: VocabStore, auth_headers: dict[str, str]
) -> None:
    # The dict cache is optional (only the frequency tie-break needs it).
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.tokenizer = tokenizer
    app.state.vocab_store = vocab_store
    client = TestClient(app, raise_server_exceptions=False)
    body = _sort(client, auth_headers, ["猫", "犬が猫を見る"])
    assert sorted(r["sequence"] for r in body["results"]) == [0, 1]


def test_requires_tokenizer(vocab_client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = vocab_client.post(
        "/v1/mining/nplus1sort", headers=auth_headers, json={"sentences": [{"text": "猫"}]}
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tokenizer_unavailable"


def test_requires_vocab_store(text_client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = text_client.post(
        "/v1/mining/nplus1sort", headers=auth_headers, json={"sentences": [{"text": "猫"}]}
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "vocab_unavailable"


def test_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/mining/nplus1sort", json={"sentences": [{"text": "猫"}]})
    assert resp.status_code == 401
