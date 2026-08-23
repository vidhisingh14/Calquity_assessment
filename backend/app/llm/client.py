"""Chat completion: one entry point, provider swappable.

Cerebras is OpenAI-compatible, so it is driven through the `openai` SDK with a
custom base_url. Gemini has its own SDK. Nothing above this layer knows which
is live -- swapping providers after the pre-Phase-5 tool-calling spike is a
config change, not a refactor.

=========================== THE HARD INVARIANT ===========================
`tools` and `response_format` are NEVER sent in the same request.

Providers handle the combination inconsistently: some ignore the schema, some
ignore the tools, some error. The failure is silent in the worst case -- you
get a well-formed JSON object that was supposed to be a tool call, and the
agent loop stalls without an obvious cause.

So `complete()` raises if both are passed. The validator, the eval judge and
signal naming are all separate no-tools calls with a JSON schema. This is
enforced by an assertion here and by a unit test, not by a comment, because a
comment does not survive the next person adding a parameter.
==========================================================================
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import get_settings
from app.errors import LLMError


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None
    # The provider's OWN representation of this assistant turn, kept verbatim.
    # Gemini 3.x requires the `thought_signature` on function-call parts to be
    # echoed back on the next request; rebuilding the turn from a normalised
    # dict silently drops it and the follow-up request 400s mid-chain. So the
    # original object is carried through and replayed unchanged.
    provider_content: Any = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class MutuallyExclusiveRequestError(LLMError):
    """Raised when tools and response_format are combined. See module docstring."""


def _guard(tools: list[dict] | None, response_format: dict | None) -> None:
    if tools and response_format:
        raise MutuallyExclusiveRequestError(
            "tools and response_format must never be sent in the same request. "
            "Providers handle the combination inconsistently and the failure is "
            "silent. Make this a separate no-tools call with a JSON schema."
        )


class ChatClient(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        temperature: float = 0.0,
    ) -> ChatResponse: ...


class CerebrasChatClient:
    def __init__(self, api_key: str | None = None, model: str | None = None,
                 base_url: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.cerebras_api_key
        self.model = model or settings.chat_model
        self.base_url = base_url or settings.cerebras_base_url
        if not self.api_key:
            raise LLMError("CEREBRAS_API_KEY is not set")

    def complete(self, messages, tools=None, response_format=None, temperature=0.0):
        _guard(tools, response_format)

        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if response_format:
            kwargs["response_format"] = response_format

        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Cerebras request failed: {exc}") from exc

        choice = resp.choices[0].message
        calls: list[ToolCall] = []
        for tc in getattr(choice, "tool_calls", None) or []:
            import json

            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        return ChatResponse(content=choice.content, tool_calls=calls, raw=resp)


class GeminiChatClient:
    """Fallback for the agent loop, and the default for judge / signal naming.

    Auth mode (Developer API key vs. Vertex AI service account) is resolved
    once per call by gemini_auth.build_client(), driven by
    settings.gemini_auth_mode. Neither this class nor its caller needs to know
    which mode is active -- that is the entire point of the seam.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.judge_model
        if settings.gemini_auth_mode == "api_key" and not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set")

    def complete(self, messages, tools=None, response_format=None, temperature=0.0):
        _guard(tools, response_format)

        from google.genai import types

        from app.llm import gemini_auth, gemini_compat

        client = gemini_auth.build_client()

        # Tool calls and tool RESULTS travel as parts in Gemini, not as separate
        # roles. Filtering by role drops the model's own tool output, after
        # which it either repeats the call forever or answers from nothing.
        system, contents = gemini_compat.to_contents(messages, types)

        config: dict[str, Any] = {"temperature": temperature}
        if system:
            config["system_instruction"] = system
        if response_format:
            config["response_mime_type"] = "application/json"
            schema = (response_format.get("json_schema") or {}).get("schema")
            if schema:
                config["response_schema"] = gemini_compat.sanitise_schema(dict(schema))
        if tools:
            # Pydantic emits additionalProperties and anyOf, both of which
            # Gemini's function-declaration parser rejects with a 400.
            config["tools"] = [types.Tool(
                function_declarations=gemini_compat.to_function_declarations(tools)
            )]

        # Free-tier limits are per MINUTE, and one agent turn costs 4-6 calls,
        # so a burst of turns trips 429 long before any daily cap. Retrying with
        # backoff is what makes the agent usable on a free key at all; without
        # it the loop reports "model unavailable" for a limit that clears in
        # seconds.
        resp = None
        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                resp = client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=types.GenerateContentConfig(**config),
                )
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                    time.sleep(2 ** attempt + 1)
                    continue
                raise LLMError(f"Gemini request failed: {exc}") from exc
        if resp is None:
            raise LLMError(
                f"Gemini rate limit not cleared after retries: {last_exc}"
            ) from last_exc

        calls: list[ToolCall] = []
        for index, fc in enumerate(resp.function_calls or []):
            # Gemini identifies calls by name; an id is synthesised so the agent
            # loop's id-based bookkeeping works unchanged.
            calls.append(ToolCall(
                id=f"{fc.name}-{index}",
                name=fc.name,
                arguments=dict(fc.args or {}),
            ))

        text = None
        try:
            text = resp.text
        except Exception:  # noqa: BLE001 - a pure tool-call turn carries no text
            text = None

        provider_content = None
        if resp.candidates:
            provider_content = resp.candidates[0].content

        return ChatResponse(content=text, tool_calls=calls, raw=resp,
                            provider_content=provider_content)



def get_chat_client() -> ChatClient:
    settings = get_settings()
    if settings.chat_provider == "gemini":
        return GeminiChatClient(model=settings.chat_model)
    return CerebrasChatClient()


def get_judge_client() -> ChatClient:
    """Deliberately not the answering model: a model grading its own output
    inflates the score."""
    settings = get_settings()
    if settings.judge_provider == "cerebras":
        return CerebrasChatClient(model=settings.judge_model)
    return GeminiChatClient(model=settings.judge_model)
