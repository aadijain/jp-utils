from fastapi.testclient import TestClient


def test_words_and_filter_by_status_endpoints(
    vocab_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = vocab_client.post(
        "/v1/vocab/words",
        headers=auth_headers,
        json={"entries": [{"lemma": "水", "reading": "みず"}]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"recorded": 1, "version": 1}

    # default statuses = unknown-only -> 水 (learnt) drops out, 火 (unknown) stays.
    resp = vocab_client.post(
        "/v1/vocab/filter-by-status",
        headers=auth_headers,
        json={"words": [{"lemma": "水", "reading": "みず"}, {"lemma": "火", "reading": "ひ"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["matched"] == [{"lemma": "火", "reading": "ひ"}]


def test_filter_by_status_lemma_only(
    vocab_client: TestClient, auth_headers: dict[str, str]
) -> None:
    vocab_client.post(
        "/v1/vocab/words",
        headers=auth_headers,
        json={"entries": [{"lemma": "人", "reading": "ひと"}]},  # learnt by default
    )
    body = {"words": [{"lemma": "人", "reading": "じん"}], "statuses": ["unknown", "seen"]}

    # Exact key: the reading mismatch surfaces 人 as unknown -> it stays.
    resp = vocab_client.post("/v1/vocab/filter-by-status", headers=auth_headers, json=body)
    assert resp.json()["matched"] == [{"lemma": "人", "reading": "じん"}]

    # Lemma-only: 人 is recognized as learnt regardless of reading -> dropped.
    resp = vocab_client.post(
        "/v1/vocab/filter-by-status",
        headers=auth_headers,
        json={**body, "match_lemma_only": True},
    )
    assert resp.json()["matched"] == []


def test_filter_by_status_set(vocab_client: TestClient, auth_headers: dict[str, str]) -> None:
    vocab_client.post(
        "/v1/vocab/words",
        headers=auth_headers,
        json={"entries": [{"lemma": "水", "reading": "みず"}]},  # learnt by default
    )
    resp = vocab_client.post(
        "/v1/vocab/filter-by-status",
        headers=auth_headers,
        json={
            "words": [{"lemma": "水", "reading": "みず"}, {"lemma": "火", "reading": "ひ"}],
            "statuses": ["unknown", "learnt"],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["matched"] == [
        {"lemma": "水", "reading": "みず"},
        {"lemma": "火", "reading": "ひ"},
    ]


def test_force_records_a_terminal_status(
    vocab_client: TestClient, auth_headers: dict[str, str]
) -> None:
    # `ignored` is not an upgrade, so it needs force=True to be written.
    resp = vocab_client.post(
        "/v1/vocab/words",
        headers=auth_headers,
        json={
            "entries": [{"lemma": "は", "reading": "は", "action": "ignored"}],
            "force": True,
        },
    )
    assert resp.json()["recorded"] == 1
    # it is now known (not unknown), so unknown-only filtering drops it.
    resp = vocab_client.post(
        "/v1/vocab/filter-by-status",
        headers=auth_headers,
        json={"words": [{"lemma": "は", "reading": "は"}]},
    )
    assert resp.json()["matched"] == []


def test_status_endpoint(vocab_client: TestClient, auth_headers: dict[str, str]) -> None:
    vocab_client.post(
        "/v1/vocab/words",
        headers=auth_headers,
        json={"entries": [{"lemma": "水", "reading": "みず"}]},
    )
    resp = vocab_client.get("/v1/vocab/status", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"count": 1, "events": 1, "version": 1}


def test_export_endpoint(vocab_client: TestClient, auth_headers: dict[str, str]) -> None:
    vocab_client.post(
        "/v1/vocab/words",
        headers=auth_headers,
        json={"entries": [{"lemma": "水", "reading": "みず"}]},
    )
    resp = vocab_client.get("/v1/vocab/export", headers=auth_headers, params={"format": "csv"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "水" in resp.text


def test_vocab_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/vocab/filter-by-status", json={"words": []})
    assert resp.status_code == 401


def test_vocab_unavailable_without_store(client: TestClient, auth_headers: dict[str, str]) -> None:
    # `client` has no vocab_store on app.state.
    resp = client.get("/v1/vocab/status", headers=auth_headers)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "vocab_unavailable"
