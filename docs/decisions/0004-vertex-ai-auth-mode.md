# ADR-0004: Vertex AI as a second Gemini auth mode

**Status:** Accepted. **Date:** 2026-08-23

## Context

ADR-0001 established that the Gemini Developer API's free tier caps at
roughly 20 requests/day/model, which blocked a full 10-run tool-calling spike
and a full 32-question eval from completing in one session. A GCP Vertex AI
service account key became available, and Vertex AI draws from a separate,
much larger quota than the Developer API free tier.

## Decision

`app/llm/gemini_auth.py` is a single seam, `build_client()`, that both
`GeminiChatClient.complete()` and `GeminiEmbedder.embed()` now call instead of
constructing `genai.Client(api_key=...)` directly. It reads
`settings.gemini_auth_mode`:

- `"api_key"` (default, unchanged behaviour) — Developer API key.
- `"vertex"` — `genai.Client(vertexai=True, project=..., location=...,
  credentials=...)`, authenticated from a downloaded GCP service account JSON
  key.

**The project id is read from the key file, not typed twice.** The service
account JSON already carries `project_id`; `VERTEX_PROJECT_ID` is optional and
only overrides it. Requiring both risked the two silently disagreeing.

**Key file handling:**
`backend/credentials/vertex-service-account.example.json` is a placeholder
committed to the repo, showing the exact shape of a real key with no real
secrets. The real file — any name, but `vertex-service-account.json` by
default — is gitignored via
`backend/credentials/*.json` + `!backend/credentials/*.example.json`, verified
with `git check-ignore` before this ADR was written: the placeholder is
tracked, the real key is not, and there is no filename collision to get wrong.

Neither `GeminiChatClient` nor `GeminiEmbedder` needed structural changes
beyond the one call site each — this is the seam the original design
(`app/llm/client.py`'s module docstring: "provider swappable... nothing above
this layer knows which is live") was built for, and it held.

## Consequence

`requirements.txt`'s `google-genai` pin was found stale during this change
(`0.8.0`, which predates the `vertexai=` client signature and was never
actually installed — the host had drifted to `2.19.0` through ad hoc installs
during earlier debugging). Corrected to `google-genai==2.19.0` and
`google-auth==2.56.3`, the versions actually exercised, so a fresh
`docker compose build` matches what was tested rather than reverting to an
untested pin.
