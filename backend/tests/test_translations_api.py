import csv
import io

from fastapi.testclient import TestClient


def _lookup(client: TestClient, headers: dict[str, str], sentences: list[str]):
    resp = client.post(
        "/v1/translations/lookup",
        headers=headers,
        json={"queries": [{"sentence": s} for s in sentences]},
    )
    assert resp.status_code == 200
    return resp.json()["results"]


def test_lookup_enqueues_then_returns_done_after_import(
    translation_client: TestClient, auth_headers: dict[str, str]
) -> None:
    results = _lookup(translation_client, auth_headers, ["お前が悪い", "はい 解散"])
    assert [r["status"] for r in results] == ["pending", "pending"]

    resp = translation_client.get("/v1/translations/export", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert [r["source"] for r in rows] == ["お前が悪い", "はい 解散"]

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["key", "source", "context", "translation", "notes"])
    writer.writerow([rows[0]["key"], "", "", "You're the one in the wrong.", "a note"])
    writer.writerow([rows[1]["key"], "", "", "", ""])  # worker error row: stays pending
    resp = translation_client.post(
        "/v1/translations/results",
        headers={**auth_headers, "Content-Type": "text/csv"},
        content=out.getvalue(),
    )
    assert resp.status_code == 200
    assert resp.json() == {"done": 1, "skipped": 1}

    results = _lookup(translation_client, auth_headers, ["お前が悪い", "はい 解散"])
    assert results[0] == {
        "status": "done",
        "translation": "You're the one in the wrong.",
        "notes": "a note",
    }
    assert results[1]["status"] == "pending"


def test_results_rejects_malformed_csv(
    translation_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = translation_client.post(
        "/v1/translations/results", headers=auth_headers, content="key,source\nabc,def\n"
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_results_csv"


def test_translations_unavailable_without_queue(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post("/v1/translations/lookup", headers=auth_headers, json={"queries": []})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "translations_unavailable"


def test_translations_require_token(translation_client: TestClient) -> None:
    resp = translation_client.get("/v1/translations/export")
    assert resp.status_code == 401
