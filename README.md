# ParcelPilot AI Support Agent

A multi-tool, multi-source AI support agent for a B2B logistics platform, with
strict layer separation. Full build spec: `parcelpilot-agent-build-spec.md`.
Design deltas and assumption sign-offs: `docs/superpowers/specs/2026-08-23-parcelpilot-agent-design.md`.

## Quick start (Docker is the source of truth)

```bash
cp .env.example .env
# fill in CEREBRAS_API_KEY / GEMINI_API_KEY in .env

docker compose up -d db
docker compose run --rm setup      # migrate + ingest
docker compose up -d --build       # api + web

# or, if you have `make`:
make setup
make up
```

### Using Vertex AI instead of the Gemini Developer API key

The Developer API's free tier caps at roughly 20 requests/day/model, which is
tight for a full eval run (see
`docs/decisions/0001-gemini-quota-and-spike-gate.md`). Vertex AI draws from a
separate, larger quota:

```bash
cp backend/credentials/vertex-service-account.example.json \
   backend/credentials/vertex-service-account.json
# paste your real downloaded GCP service account key's JSON into that file
```

Then in `.env`, set `GEMINI_AUTH_MODE=vertex`. The project id is read from the
key file itself, so `VERTEX_PROJECT_ID` only needs setting if you want to
override it. `backend/credentials/vertex-service-account.json` is gitignored;
the `.example.json` placeholder is the only one tracked. Details:
`docs/decisions/0004-vertex-ai-auth-mode.md`.

- API: http://localhost:8000 (docs at `/docs`, health at `/healthz`)
- Web: http://localhost:5173

`/healthz` is the ingestion sanity check — it reports row counts, the dataset
snapshot time, and how many policy terms are verified vs. still drafted.

## Local dev on Windows (without full Docker rebuild loops)

Backend, with a local Postgres started via `docker compose up -d db`:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
copy .env backend\.env   # pydantic-settings resolves .env relative to cwd
cd backend
python -m scripts.migrate
python -m ingestion.run_ingest
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev   # proxies /chat, /users, /signals, /actions, /healthz to :8000
```

## Tests

```bash
cd backend
python -m scripts.check_layers   # the four layer-boundary rules, as one command
pytest tests/unit -q             # no database needed
pytest tests/integration -q      # needs a Postgres reachable via TEST_DATABASE_URL
pytest tests/ -q                 # everything
```

Blocking gates (fail the build, not just a review comment): the layer check,
15 cross-account leak tests, 6 tier-5-exclusion tests, the `tools`+
`response_format` mutual-exclusion guard, and 8 golden-set rows marked
`blocking: true` (four leak checks, one positive internal-scope control, two
ticket-resolution traps, the confirmation gate).

## Evaluation

```bash
cd backend
python -m eval.run_eval                     # all 32 golden questions
python -m eval.run_eval --only g05_northstar_cancel_fee
```

Scores verified and unverified golden rows **separately** — every question in
`data/golden/golden_set.yaml` is signed off (`unverified: false`) as of
2026-08-23, but the harness keeps the split so a future draft addition can't
quietly inflate the headline number.

**Known constraint:** the free Gemini tier caps at roughly 20 requests/day per
model. A full 32-question eval run and a full 10-run tool-calling spike both
need more headroom than that gives in one sitting — see
`docs/decisions/0001-gemini-quota-and-spike-gate.md` for what was and wasn't
verified, and with what evidence.

## Proactive detection

```bash
cd backend
python -m jobs.detect_signals
```

Rules-first (`app/services/detection.py`), one LLM call per signal only to
write a human title — detection itself never touches a model, so results are
reproducible run to run. On the real dataset this finds 7 signals: 2 SLA
breaches, 1 security incident, 2 known-issue matches, 2 unattended-P1s.

## Repository layout

Mirrors the layer diagram in `docs/architecture-note.md`:

```
backend/app/{api,auth,agent,tools,services,repositories,llm,observability}
backend/{ingestion,jobs,eval,scripts,migrations,tests}
frontend/src/{api,components,hooks,state}
data/{raw,golden,terms_overrides.yaml}
docs/{architecture-note.md,product-note.md,ai-tool-usage.md,decisions/}
```

## Demo users (mocked auth, real authorization)

Seeded in `backend/migrations/006_users.sql`, selectable from the web UI's
role switcher:

| user_id | role | account |
|---|---|---|
| `u_northstar` | customer | ACCT-001 Northstar Logistics |
| `u_lumen` | customer | ACCT-002 LumenWorks |
| `u_beacon` | customer | ACCT-003 Beacon Retail |
| `u_agent` | support_agent | — |
| `u_ops` | ops_lead | — |

Identity is mocked via an `X-User-Id` header; authorization is enforced in SQL
(`app/repositories/*.py`), never in a prompt — see the cross-account leak
tests for the proof.
