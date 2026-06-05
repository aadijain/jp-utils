"""Application settings, loaded from the environment.

Pydantic is the backend-only validation layer (the cross-process contract in
`shared/` stays plain dataclasses). Settings are read from `JP_UTILS_*` env vars
or a local `.env` file. `get_settings` is cached so the same instance is reused;
tests override it via `app.dependency_overrides`.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JP_UTILS_",
        env_file=".env",
        extra="ignore",
    )

    service_name: str = "jp-utils"
    version: str = "0.1.0"

    # Bearer token required on every /v1 route. Empty means auth is unconfigured
    # and the server fails closed (see app.auth).
    api_token: str = ""

    # Read-only dictionary cache location. Empty -> dicts.paths.default_cache_path().
    dict_cache_path: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
