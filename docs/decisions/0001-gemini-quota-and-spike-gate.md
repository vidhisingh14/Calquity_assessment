# ADR-0001: Cerebras unusable, Gemini free-tier quota constrains the spike

**Status:** Accepted
**Date:** 2026-08-23

## Context

The pre-Phase-5 gate required a 3-hop tool-calling spike (`lookup_records` →
`search_documents` → `evaluate_policy`), 10 runs, ≥9/10 pass rate, else flip
`CHAT_PROVIDER`.

**Cerebras:** the configured API key can see `gpt-oss-120b` and `gemma-4-31b`
in its model list, but every request to either returns `402 Payment required`.
This is an account/billing state, not a capability question — Cerebras is
unusable on this key regardless of model choice.

**Gemini:** flipping to Gemini per the gate surfaced two real bugs, both fixed
in `app/llm/gemini_compat.py` and `app/llm/client.py`:

1. Pydantic's `model_json_schema()` emits `additionalProperties` and
   `anyOf`-with-null, both rejected by Gemini's function-declaration parser
   with a 400. Fixed with a schema sanitiser.
2. Gemini represents tool calls and tool results as *parts* on `model`/`user`
   turns, not as OpenAI's separate `tool` role. Naively adapting the OpenAI
   message shape drops the model's own tool output, and Gemini 3.x additionally
   requires `thought_signature` to be echoed back on the next request or it
   400s mid-chain. Fixed by carrying the provider's own turn object through
   verbatim instead of reconstructing it.

With both fixed, the loop runs correctly: the Phase 5 acceptance test (the
Northstar/ORD-1001 question, end to end through `/chat`) passed on every
field, including the KI-211 caveat and the full 4-tool chain.

**Then free-tier quota ran out.** Across the debugging and spike attempts,
`gemini-2.5-flash`, `gemini-3.5-flash`, and `gemini-3.6-flash` were each driven
into `429 RESOURCE_EXHAUSTED`. The failures are quota, not capability: every
run that completed before quota ran out produced a correct verdict
(`no_fee` / `contract_waiver` / `override_applied=True`) with no invented tool
names and no invalid arguments. The largest single spike run (5 calls) needed
before rate-limiting cut in showed 2/2 verdict-correct.

## Decision

- Keep `CHAT_PROVIDER=gemini`. Cerebras is not a fallback option on this key
  (billing, not capability) so the gate's "else flip provider" branch is moot
  here — there is nowhere to flip to.
- Ship the client fixes (schema sanitiser, verbatim turn replay,
  429-with-backoff retry) as permanent, not spike scaffolding. They are
  required for Gemini tool calling to work at all, independent of quota.
- **The formal 9/10 spike score is not recorded as passed**, because it could
  not be completed against the daily quota available. This is stated plainly
  rather than papered over with a partial number presented as the full result.
- **Update (2026-08-23, same day):** a Vertex AI service account key became
  available. `app/llm/gemini_auth.py` adds a second auth mode
  (`GEMINI_AUTH_MODE=vertex`) alongside the Developer API key mode, selected
  by config and transparent to `GeminiChatClient` and `GeminiEmbedder` — both
  already called through the shared `gemini_auth.build_client()` seam, so
  neither needed to change beyond that call site. Vertex AI has its own quota,
  separate from the Developer API free tier, which is the actual fix for this
  ADR rather than a workaround. See `docs/decisions/0004-vertex-ai-auth-mode.md`.
- Re-run `python -m scripts.spike_tool_calling --runs 10` on Vertex once the
  service account key is in place, and update this ADR with the actual score
  before treating the gate as closed.

## Consequence

The system is demonstrably working — Phase 5's acceptance test is real
evidence, not a mock — but the specific numeric gate from the brainstorm is
open pending quota. Anyone reviewing this should re-run the spike before
relying on Gemini tool-calling reliability at a volume the free tier cannot
sustain (the 32-question eval set, for instance, needs its own quota budget
or a paid key).
