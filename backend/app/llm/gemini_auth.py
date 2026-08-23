"""One place that decides how to build a `genai.Client`.

Two auth modes, one call site each in client.py and embeddings.py. Adding a
third mode (workload identity, a different project per environment, ...) means
touching this file only.
"""

from __future__ import annotations

import pathlib

from app.config import get_settings
from app.errors import LLMError


def build_client():
    """Returns a configured `google.genai.Client`, Developer API or Vertex."""
    from google import genai

    settings = get_settings()

    if settings.gemini_auth_mode == "vertex":
        return _vertex_client(settings)

    if not settings.gemini_api_key:
        raise LLMError(
            "GEMINI_API_KEY is not set and GEMINI_AUTH_MODE is 'api_key'. "
            "Either set the key, or set GEMINI_AUTH_MODE=vertex and configure "
            "the service account instead."
        )
    return genai.Client(api_key=settings.gemini_api_key)


def _vertex_client(settings):
    import json

    from google import genai
    from google.oauth2 import service_account

    key_path = pathlib.Path(settings.vertex_credentials_path)
    if not key_path.is_absolute():
        # Resolved relative to backend/, matching how the app is run both
        # locally (cwd = backend/) and in the container (WORKDIR /app).
        key_path = pathlib.Path(__file__).resolve().parent.parent.parent / key_path

    if not key_path.exists():
        raise LLMError(
            f"GEMINI_AUTH_MODE=vertex but no service account key found at "
            f"{key_path}. Copy "
            f"backend/credentials/vertex-service-account.example.json to "
            f"backend/credentials/vertex-service-account.json and paste in "
            f"your real key, or point VERTEX_CREDENTIALS_PATH at it."
        )

    # The key file names the project it belongs to. Falling back to it (rather
    # than requiring VERTEX_PROJECT_ID as a second, separately-typed value)
    # removes a way for the two to quietly disagree.
    project_id = settings.vertex_project_id
    if not project_id:
        try:
            project_id = json.loads(key_path.read_text(encoding="utf-8")).get("project_id")
        except (json.JSONDecodeError, OSError):
            project_id = None
        if not project_id:
            raise LLMError(
                f"GEMINI_AUTH_MODE=vertex: VERTEX_PROJECT_ID is not set and "
                f"{key_path} has no readable project_id field."
            )

    credentials = service_account.Credentials.from_service_account_file(
        str(key_path),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )

    return genai.Client(
        vertexai=True,
        project=project_id,
        location=settings.vertex_location,
        credentials=credentials,
    )
