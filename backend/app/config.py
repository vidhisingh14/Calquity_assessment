"""Typed settings, parsed exactly once.

There is no `os.getenv` anywhere else in the codebase. If you need a new knob,
add it here so every configurable value is discoverable in one file.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql://parcelpilot:parcelpilot@localhost:5432/parcelpilot"

    # --- Chat: the agent loop ---------------------------------------------
    chat_provider: Literal["cerebras", "gemini"] = "gemini"
    # "-latest"/"3.x" alias names (e.g. gemini-flash-latest, gemini-3.1-flash-
    # lite) exist only on the Developer API. Vertex AI's model catalog is
    # versioned differently and 404s on those aliases, so the default here is
    # a name that resolves in BOTH auth modes.
    chat_model: str = "gemini-2.5-flash"
    cerebras_api_key: str = ""
    cerebras_base_url: str = "https://api.cerebras.ai/v1"

    # --- Embeddings --------------------------------------------------------
    # Cerebras has no embeddings endpoint. gemini-embedding-001 supports
    # Matryoshka output dims and 1536 matches VECTOR(1536) exactly.
    embed_provider: Literal["gemini"] = "gemini"
    embed_model: str = "gemini-embedding-001"
    embed_dim: int = 1536
    gemini_api_key: str = ""

    # --- Gemini auth mode ---------------------------------------------------
    # "api_key"  -> the Gemini Developer API, gated at ~20 requests/day/model
    #               on the free tier. This is what blocked the full spike and
    #               eval run -- see docs/decisions/0001.
    # "vertex"   -> Vertex AI, authenticated with a GCP service account key.
    #               Separate, much larger quota from the Developer API's free
    #               tier, which is why this exists as a second mode rather
    #               than just a different key in the same slot.
    gemini_auth_mode: Literal["api_key", "vertex"] = "api_key"
    vertex_project_id: str = ""
    vertex_location: str = "us-central1"
    # Path to the downloaded service account JSON. Copy
    # backend/credentials/vertex-service-account.example.json to
    # backend/credentials/vertex-service-account.json (gitignored) and paste
    # the real key contents in; this setting just needs to point at it.
    vertex_credentials_path: str = "credentials/vertex-service-account.json"

    # --- Judge / signal naming --------------------------------------------
    judge_provider: Literal["gemini", "cerebras"] = "gemini"
    judge_model: str = "gemini-2.5-flash"

    # --- Agent behaviour ---------------------------------------------------
    max_agent_steps: int = 8
    pending_action_ttl_minutes: int = 15
    retrieval_k: int = 8
    enable_deprecated_docs_for_internal: bool = True
    log_level: str = "info"

    # --- Business calendar (assumption A3) ---------------------------------
    # "business hours" and "business days" are never defined by the source
    # documents. These are a stated assumption, not something read from them.
    business_tz: str = "Asia/Kolkata"
    business_day_start: str = "09:00"
    business_day_end: str = "18:00"

    data_dir: str = "./data"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
