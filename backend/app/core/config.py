"""Application settings.

All configuration comes from environment variables (or an ``.env`` file in
development). Required variables are validated at startup so the process
fails fast with a clear message instead of failing on first use.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "MPSTT CRM API"
    env: Literal["development", "test", "staging", "production"] = Field(alias="APP_ENV")
    debug: bool = False

    # Database (asyncpg URL, e.g. postgresql+asyncpg://user:pass@host:5432/db)
    database_url: str = Field(alias="DATABASE_URL")

    # CORS allowlist, comma separated origins
    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")

    # Supabase project (auth + storage)
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    # Legacy HS256 JWT secret. Either this or the project's JWKS must be usable
    # to verify access tokens in non-development environments.
    supabase_jwt_secret: str = Field(default="", alias="SUPABASE_JWT_SECRET")
    # Service-role key: server-side only, used for Storage and admin user
    # invitation. NEVER shipped to the browser.
    supabase_service_role_key: str = Field(default="", alias="SUPABASE_SERVICE_ROLE_KEY")
    # Expected JWT audience for Supabase access tokens.
    supabase_jwt_aud: str = Field(default="authenticated", alias="SUPABASE_JWT_AUD")

    # Storage backend: "supabase" in real deployments, "local" for dev/tests.
    storage_backend: Literal["supabase", "local"] = Field(default="local", alias="STORAGE_BACKEND")
    local_storage_dir: str = Field(default="var/storage", alias="LOCAL_STORAGE_DIR")

    # Require aal2 (TOTP MFA) for admin high-risk actions. On in production.
    require_admin_mfa: bool = Field(default=False, alias="REQUIRE_ADMIN_MFA")

    request_timezone: str = "Asia/Karachi"

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must be a postgresql+asyncpg:// URL")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_for_env(self) -> None:
        """Extra safety checks that only make sense per environment."""
        if self.env in ("staging", "production"):
            problems = []
            if not self.supabase_url:
                problems.append("SUPABASE_URL is required")
            # Tokens are verified either against the project's JWKS (ES256 —
            # the current Supabase default, needs only SUPABASE_URL) or against
            # the legacy HS256 secret. One of the two must be available.
            if not self.supabase_url and not self.supabase_jwt_secret:
                problems.append(
                    "Token verification needs SUPABASE_URL (JWKS) or SUPABASE_JWT_SECRET"
                )
            if self.storage_backend != "supabase":
                problems.append("STORAGE_BACKEND must be 'supabase'")
            if self.env == "production" and not self.require_admin_mfa:
                problems.append("REQUIRE_ADMIN_MFA must be true in production")
            if problems:
                raise RuntimeError("Invalid configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()  # type: ignore[call-arg]
    settings.validate_for_env()
    return settings
