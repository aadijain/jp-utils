import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app

TEST_TOKEN = "test-token"


@pytest.fixture
def settings() -> Settings:
    return Settings(api_token=TEST_TOKEN)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    # Let the catch-all exception handler run instead of re-raising in the test.
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}
