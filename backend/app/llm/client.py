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
    """Fallback for the agent loop, and the default for judge / signal naming."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.judge_model
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set")

    def complete(self, messages, tools=None, response_format=None, temperature=0.0):
        _guard(tools, response_format)

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)

        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        contents = [
            types.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[types.Part(text=str(m.get("content") or ""))],
            )
            for m in messages
            if m.get("role") in ("user", "assistant")
        ]

        config: dict[str, Any] = {"temperature": temperature}
        if system:
            config["system_instruction"] = system
        if response_format:
            config["response_mime_type"] = "application/json"
            schema = (response_format.get("json_schema") or {}).get("schema")
            if schema:
                config["response_schema"] = schema
        if tools:
            config["tools"] = [types.Tool(function_declarations=[
                t["function"] for t in tools
            ])]

        try:
            resp = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(**config),
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Gemini request failed: {exc}") from exc

        calls: list[ToolCall] = []
        for fc in (resp.function_calls or []):
            calls.append(ToolCall(id=fc.id or fc.name, name=fc.name,
                                  arguments=dict(fc.args or {})))

        return ChatResponse(content=resp.text, tool_calls=calls, raw=resp)


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
