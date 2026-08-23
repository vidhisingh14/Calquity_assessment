# AI coding tools used

**Claude Code (Claude Opus 5 / Sonnet 5)**, used for the entire build:
architecture design (via the `superpowers:brainstorming` skill, producing the
design doc under `docs/superpowers/specs/`), all backend and frontend code,
the migration schema, the ingestion pipeline, the curated `terms_overrides.yaml`
and `golden_set.yaml` review tables, and this documentation.

Notable points on how it was used:

- The design was **not** taken as a straight implementation of the build spec.
  Several places where the spec's assumptions didn't match the real data pack
  were surfaced explicitly (§0 of the design doc: 12 numbered assumptions),
  proposed with reasoning, and required human sign-off before Phase 4 began.
- The terms file and golden set were drafted by the agent from one reading of
  the source PDFs, then marked `unverified: true` throughout and handed back
  for human review with the literal source sentence next to every value —
  specifically to avoid the agent grading its own drafted answer key.
- Real bugs were found and fixed during the build, not just features added:
  a layer-boundary violation caught by the automated check on its first run,
  an access-control bug where internal roles could never retrieve any
  contract (a NULL account scope was treated as "unscoped only" instead of
  "unrestricted"), a validator false-positive that downgraded correct answers
  for quoting timestamps, and two provider-compatibility bugs in Gemini tool
  calling (schema dialect, `thought_signature` requirements) that would have
  made the agent loop silently non-functional on that provider.
- Web search was used to verify time-sensitive facts rather than relying on
  training data: current Cerebras model availability, Gemini embedding
  dimensionality options, and comparative tool-calling reliability between
  candidate models — each cited with sources at the time.
