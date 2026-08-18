"""Batch-size guard on the batch-first endpoints (see `app/api/v1/limits.py`)."""

import pytest
from fastapi.testclient import TestClient

from app.api.v1.limits import MAX_BATCH, check_batch
from app.errors import APIError


def test_check_batch_allows_a_deck_sized_batch() -> None:
    """Whole-deck batches are the normal case, not an abuse to be throttled."""
    check_batch(["x"] * 2000, "texts")  # must not raise


def test_check_batch_rejects_past_the_cap() -> None:
    with pytest.raises(APIError) as exc:
        check_batch(["x"] * (MAX_BATCH + 1), "texts")
    assert exc.value.status_code == 413
    assert exc.value.code == "batch_too_large"
    assert "texts" in exc.value.message


def test_endpoint_returns_the_coded_error(
    text_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = text_client.post(
        "/v1/text/tokenize",
        json={"texts": ["猫"] * (MAX_BATCH + 1)},
        headers=auth_headers,
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "batch_too_large"
