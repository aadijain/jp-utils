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


@pytest.fixture(scope="session")
def tokenizer():
    """One real SudachiPy tokenizer, reused across tests (dict load is slow)."""
    from app.text.tokenizer import Tokenizer

    return Tokenizer()


@pytest.fixture
def text_client(settings: Settings, tokenizer) -> TestClient:
    """Client with the tokenizer injected on app.state (no lifespan needed)."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.tokenizer = tokenizer
    return TestClient(app, raise_server_exceptions=False)
