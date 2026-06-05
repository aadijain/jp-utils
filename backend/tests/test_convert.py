from fastapi.testclient import TestClient

from app.text.convert import convert, kata_to_hira
from shared.text import Conversion


def test_kata_to_hira() -> None:
    assert kata_to_hira("タベル") == "たべる"
    assert kata_to_hira("コーヒー") == "こーひー"  # long-vowel mark preserved


def test_convert_kana() -> None:
    assert convert("たべる", Conversion.HIRA_TO_KATA) == "タベル"
    assert convert("タベル", Conversion.KATA_TO_HIRA) == "たべる"


def test_convert_width() -> None:
    assert convert("ｱｲｳ", Conversion.TO_FULLWIDTH) == "アイウ"
    assert convert("ＡＢＣ１２３", Conversion.TO_HALFWIDTH) == "ABC123"


def test_convert_endpoint(text_client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = text_client.post(
        "/v1/text/convert",
        headers=auth_headers,
        json={"texts": ["たべる", "すし"], "conversion": "hira_to_kata"},
    )

    assert resp.status_code == 200
    assert resp.json()["results"] == ["タベル", "スシ"]


def test_convert_rejects_invalid_conversion(
    text_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = text_client.post(
        "/v1/text/convert",
        headers=auth_headers,
        json={"texts": ["猫"], "conversion": "nope"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_convert_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/text/convert", json={"texts": ["猫"], "conversion": "hira_to_kata"})
    assert resp.status_code == 401
