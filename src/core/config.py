"""
@file src/core/config.py
@description Centralized application configuration and environment variable validation
using Pydantic BaseSettings.
"""

from typing import Annotated, List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded securely from environment variables.
    """
    supabase_url: str = Field(..., validation_alias="SUPABASE_URL")
    supabase_anon_key: str = Field(..., validation_alias="SUPABASE_ANON_KEY")
    supabase_secret_key: str = Field(..., validation_alias="SUPABASE_SERVICE_ROLE_KEY")
    database_url: str = Field(..., validation_alias="DATABASE_URL")
    supabase_jwks_url: str = Field(..., validation_alias="SUPABASE_JWKS_URL")
    supabase_media_bucket: str = Field("memoir-media", validation_alias="SUPABASE_BUCKET_NAME")
    
    # Flexible LLM Configuration for Groq / ExperientialLabs / OpenAI
    llm_api_key: Optional[str] = Field(None, validation_alias="LLM_API_KEY")
    llm_base_url: str = Field("https://api.groq.com/openai/v1", validation_alias="LLM_BASE_URL")
    llm_model: str = Field("llama-3.1-8b-instant", validation_alias="LLM_MODEL")
    
    media_max_bytes: int = Field(52_428_576, validation_alias="MEDIA_MAX_BYTES")
    media_signed_url_ttl: int = Field(300, validation_alias="MEDIA_SIGNED_URL_TTL")
    
    cors_origins: Annotated[List[str], NoDecode] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        validation_alias="CORS_ORIGINS"
    )
    frontend_url: str = Field(
        "http://localhost:3000", validation_alias="FRONTEND_URL"
    )
    share_link_base_url: str = Field(
        "http://localhost:3000/live", validation_alias="SHARE_LINK_BASE_URL"
    )

    @field_validator("share_link_base_url", mode="before")
    @classmethod
    def normalize_share_link_base_url(cls, v: str) -> str:
        # The only public reader route is /live/[token]. A base URL ending in
        # /share produces links that 404, so fail fast instead of issuing them.
        base = str(v or "").strip().rstrip("/")
        if not base.endswith("/live"):
            raise ValueError("SHARE_LINK_BASE_URL must end with /live (public reader route).")
        return base

    @field_validator("cors_origins", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | List[str]) -> List[str]:
        import json
        if isinstance(v, str):
            raw = v.strip()
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return [str(i).strip() for i in parsed if str(i).strip()]
                except Exception:
                    pass
            return [i.strip() for i in raw.split(",") if i.strip()]
        elif isinstance(v, list):
            return v
        return ["http://localhost:3000"]

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore"
    )


settings = Settings()

STORAGE_TIER_HOT = "hot"
STORAGE_TIER_COLD = "cold"

TRANSCRIPTION_STATUS_PENDING = "pending"
TRANSCRIPTION_STATUS_COMPLETED = "completed"
TRANSCRIPTION_STATUS_FAILED = "failed"

SUPABASE_JWKS_URL = settings.supabase_jwks_url