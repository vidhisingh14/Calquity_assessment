"""Embeddings: a swappable seam with one real implementation.

Cerebras has no embeddings endpoint, so embeddings come from Gemini's
`gemini-embedding-001`, whose Matryoshka output dimension is set to 1536 to
match the VECTOR(1536) column exactly.

TASK TYPE MATTERS. Gemini embeddings are task-typed: a passage stored for
retrieval and a query searching for it are embedded differently
(RETRIEVAL_DOCUMENT vs RETRIEVAL_QUERY). Using one type for both is a silent
recall loss -- nothing errors, results just get quietly worse. So the protocol
takes the task type explicitly rather than defaulting it.
"""

from __future__ import annotations

import hashlib
import math
import time
from typing import Literal, Protocol

from app.config import get_settings
from app.errors import LLMError

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str], task_type: TaskType) -> list[list[float]]: ...


class GeminiEmbedder:
    """Developer API free tier is 100 RPM; Vertex AI has its own, separate
    quota. Ingestion is a one-off batch of a few hundred chunks either way, so
    a modest batch size plus linear backoff is sufficient in both modes.

    Auth mode is resolved by gemini_auth.build_client(), the same seam
    GeminiChatClient uses -- this class does not need to know which is active.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 dim: int | None = None, batch_size: int = 32) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.embed_model
        self.dim = dim or settings.embed_dim
        self.batch_size = batch_size
        if settings.gemini_auth_mode == "api_key" and not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set; embeddings unavailable")

    def embed(self, texts: list[str], task_type: TaskType) -> list[list[float]]:
        from google.genai import types

        from app.llm import gemini_auth

        client = gemini_auth.build_client()
        vectors: list[list[float]] = []

        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            for attempt in range(5):
                try:
                    result = client.models.embed_content(
                        model=self.model,
                        contents=batch,
                        config=types.EmbedContentConfig(
                            task_type=task_type,
                            output_dimensionality=self.dim,
                        ),
                    )
                    vectors.extend([list(e.values) for e in result.embeddings])
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 4:
                        raise LLMError(f"Gemini embedding failed: {exc}") from exc
                    time.sleep(2 * (attempt + 1))

        if len(vectors) != len(texts):
            raise LLMError(
                f"Embedding count mismatch: sent {len(texts)}, got {len(vectors)}"
            )
        return vectors


class FakeEmbedder:
    """Deterministic hash-derived vectors, for tests only.

    ================== READ THIS BEFORE USING IT IN A TEST ==================
    These vectors carry NO SEMANTIC STRUCTURE. Similar sentences do not get
    similar vectors -- the values are a hash.

    That makes this fine for PIPELINE and PLUMBING tests: does ingestion store
    the right number of rows, does the scope filter appear in the SQL, does a
    query round-trip.

    It makes it USELESS for ranking tests. A test that retrieves through this
    embedder and then asserts on result ORDER is asserting on noise, and will
    pass or fail for reasons unrelated to the ranking logic. Ranking and
    authority-promotion tests must build the candidate set directly and call
    the ranking function, with no vector search in the loop.
    ========================================================================
    """

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or get_settings().embed_dim

    def embed(self, texts: list[str], task_type: TaskType) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            raw = [
                (digest[i % len(digest)] / 255.0) - 0.5 for i in range(self.dim)
            ]
            norm = math.sqrt(sum(v * v for v in raw)) or 1.0
            out.append([v / norm for v in raw])
        return out


def get_embedder() -> Embedder:
    return GeminiEmbedder()
