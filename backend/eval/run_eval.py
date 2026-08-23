"""Golden-set evaluation harness.

    python -m eval.run_eval [--limit N] [--only ID,ID,...]

Scoring is programmatic wherever possible (citations, escalation flag,
override flag, structured verdict fields) and LLM-judged only for prose
correctness (judge_rubric), per the golden set's own assertion model.

VERIFIED vs UNVERIFIED are reported as separate figures. A question whose
`unverified: true` flag is still set was drafted by the coding agent and not
signed off by a human -- scoring it in the same bucket as a verified question
would let self-consistency masquerade as correctness.

Results are written to eval/results/<timestamp>_<prompt_version>.json and
committed, so the score is attributable to a prompt version over time.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from datetime import datetime, timezone
from typing import Any

import yaml

from app.agent import loop, prompts
from app.auth.context import AuthContext
from app.repositories import accounts_repo, actions_repo, system_repo, users_repo
from app.services import chat as chat_service
from eval.judge import judge_answer

GOLDEN_PATH = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "golden" / "golden_set.yaml"
RESULTS_DIR = pathlib.Path(__file__).resolve().parent / "results"

# role+account -> seeded user_id (backend/migrations/006_users.sql)
_ROLE_ACCOUNT_TO_USER = {
    ("customer", "ACCT-001"): "u_northstar",
    ("customer", "ACCT-002"): "u_lumen",
    ("customer", "ACCT-003"): "u_beacon",
    ("support_agent", None): "u_agent",
    ("ops_lead", None): "u_ops",
}


def _resolve_user(question: dict[str, Any]) -> AuthContext:
    key = (question["role"], question.get("account"))
    user_id = _ROLE_ACCOUNT_TO_USER.get(key)
    if user_id is None:
        raise ValueError(f"No seeded user for {key} in {question['id']}")
    row = users_repo.get_user(user_id)
    return AuthContext(user_id=row["user_id"], role=row["role"],
                       account_id=row["account_id"])


def _check_verdict(expected: dict, verdicts: list[dict]) -> tuple[bool, str]:
    if not verdicts:
        return False, "no verdict was produced"
    actual = verdicts[0]
    for key, want in expected.items():
        got = actual.get(key)
        if key == "amount_inr" and got is not None and want is not None:
            if abs(float(got) - float(want)) > 0.01:
                return False, f"{key}: expected {want}, got {got}"
            continue
        if got != want:
            return False, f"{key}: expected {want!r}, got {got!r}"
    return True, "ok"


def _check_sources(expected: dict, sources: list[dict], answer: str) -> tuple[bool, str]:
    cited = {s.get("doc_id") for s in sources if s.get("doc_id")}
    # Tier-4 citation convention: ticket:TKT-450. Not produced by the current
    # tool layer (no explicit ticket-citation mechanism yet), so must_not_cite
    # on a ticket id is checked against the answer text as a substring guard.
    for doc_id in expected.get("must_cite", []):
        if doc_id not in cited:
            return False, f"must_cite {doc_id} not in sources {sorted(cited)}"
    for doc_id in expected.get("must_not_cite", []):
        if doc_id.startswith("ticket:"):
            ticket_id = doc_id.split(":", 1)[1]
            if ticket_id in answer:
                return False, f"must_not_cite {doc_id}: ticket id appears in answer"
            continue
        if doc_id in cited:
            return False, f"must_not_cite {doc_id} but it is in sources"
    return True, "ok"


def _check_answer(expected: dict, answer: str) -> tuple[bool, str]:
    for s in expected.get("must_not_contain", []):
        if s.lower() in answer.lower():
            return False, f"must_not_contain {s!r} but it appears in the answer"
    for s in expected.get("must_contain", []):
        if s.lower() not in answer.lower():
            return False, f"must_contain {s!r} but it is missing"
    return True, "ok"


def _check_behaviour(expected: dict, envelope: dict, steps: list) -> tuple[bool, str]:
    tools = [s.tool for s in steps]
    if "escalation_offered" in expected:
        if envelope["escalation_offered"] != expected["escalation_offered"]:
            return False, (f"escalation_offered: expected "
                           f"{expected['escalation_offered']}, got "
                           f"{envelope['escalation_offered']}")
    if "min_tool_calls" in expected and len(steps) < expected["min_tool_calls"]:
        return False, f"min_tool_calls: expected >= {expected['min_tool_calls']}, got {len(steps)}"
    if "tool_sequence_contains" in expected:
        missing = [t for t in expected["tool_sequence_contains"] if t not in tools]
        if missing:
            return False, f"tool_sequence_contains: missing {missing}"
    if "pending_action" in expected:
        pa = envelope.get("pending_action")
        want = expected["pending_action"]
        if want.get("returned") and pa is None:
            return False, "pending_action expected but none returned"
        if want.get("type") and (pa or {}).get("action_type") != want["type"]:
            return False, f"pending_action type mismatch: {(pa or {}).get('action_type')}"
    return True, "ok"


def _run_confirmation_gate(question: dict, ctx: AuthContext, envelope: dict) -> tuple[bool, list[str]]:
    """g31's post_actions: confirm, confirm again, expire+confirm."""
    notes = []
    pending = envelope.get("pending_action")
    if not pending or "token" not in pending:
        return False, ["no pending_action token to confirm"]

    from app.agent import confirmation

    token = pending["token"]
    before = actions_repo.count_escalations()

    ok = True
    for step in question.get("post_actions", []):
        action = step["action"]
        if action == "confirm":
            confirmation.confirm(token, ctx.user_id)
            total = actions_repo.count_escalations()
            want = step.get("expect_escalations_total")
            if want is not None and total != before + max(0, want - before - (total - before - 1)):
                pass  # coarse check below is the real assertion
            if want is not None and total != want:
                ok = False
                notes.append(f"after confirm: expected {want} total escalations, got {total}")
        elif action == "expire_token_via_db":
            actions_repo.expire_token_for_test(token)
        elif action == "confirm_expired_token":
            try:
                confirmation.confirm(token, ctx.user_id)
                ok = False
                notes.append("expired token confirm should have raised")
            except Exception:  # noqa: BLE001
                notes.append("expired token correctly refused")
    return ok, notes


def _run_one(question: dict, prompt_version: str) -> dict[str, Any]:
    ctx = _resolve_user(question)
    snapshot = system_repo.get_snapshot_time()
    account_name = None
    if ctx.account_id:
        row = accounts_repo.get_account(ctx.account_id, ctx.account_id)
        account_name = row["account_name"] if row else None

    started = time.perf_counter()
    turn = loop.run_turn(
        message=question["question"], ctx=ctx, snapshot_time=snapshot,
        session_id=f"eval-{question['id']}", history=[], account_name=account_name,
    )
    elapsed = time.perf_counter() - started

    envelope = {
        "answer": turn.answer, "sources": turn.sources,
        "escalation_offered": (
            any(v.get("outcome") == "undecidable" for v in turn.verdicts)
            or turn.budget_exhausted
        ),
        "pending_action": turn.pending_action,
    }

    checks: list[tuple[str, bool, str]] = []

    if "expect_verdict" in question:
        ok, detail = _check_verdict(question["expect_verdict"], turn.verdicts)
        checks.append(("verdict", ok, detail))
    if "expect_sources" in question:
        ok, detail = _check_sources(question["expect_sources"], turn.sources, turn.answer)
        checks.append(("sources", ok, detail))
    if "expect_answer" in question:
        ok, detail = _check_answer(question["expect_answer"], turn.answer)
        checks.append(("answer_substrings", ok, detail))
    if "expect_behaviour" in question:
        ok, detail = _check_behaviour(question["expect_behaviour"], envelope, turn.steps)
        checks.append(("behaviour", ok, detail))

    if "post_actions" in question:
        ok, notes = _run_confirmation_gate(question, ctx, envelope)
        checks.append(("confirmation_gate", ok, "; ".join(notes)))

    judged = None
    if "judge_rubric" in question:
        judged = judge_answer(question["question"], turn.answer, question["judge_rubric"])
        checks.append(("judge", bool(judged.get("meets_rubric")), judged.get("reasoning", "")))

    programmatic_pass = all(ok for _, ok, _ in checks if _ != "judge")
    overall_pass = all(ok for _, ok, _ in checks)

    return {
        "id": question["id"], "category": question["category"],
        "unverified": question.get("unverified", True),
        "blocking": question.get("blocking", False),
        "programmatic_pass": programmatic_pass,
        "overall_pass": overall_pass,
        "checks": [{"name": n, "pass": ok, "detail": d} for n, ok, d in checks],
        "tool_sequence": [s.tool for s in turn.steps],
        "answer": turn.answer,
        "seconds": round(elapsed, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", type=str, default=None)
    args = parser.parse_args(argv)

    golden = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    questions = golden["questions"]
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]
    if args.limit:
        questions = questions[: args.limit]

    results = []
    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q['id']} ... ", end="", flush=True)
        try:
            result = _run_one(q, prompts.PROMPT_VERSION)
        except Exception as exc:  # noqa: BLE001 - a crash is a failed question
            result = {"id": q["id"], "category": q["category"],
                      "unverified": q.get("unverified", True),
                      "blocking": q.get("blocking", False),
                      "programmatic_pass": False, "overall_pass": False,
                      "checks": [{"name": "execution", "pass": False, "detail": str(exc)}],
                      "tool_sequence": [], "answer": "", "seconds": 0.0}
        results.append(result)
        print("PASS" if result["overall_pass"] else "FAIL")

    verified = [r for r in results if not r["unverified"]]
    unverified = [r for r in results if r["unverified"]]
    blocking = [r for r in results if r["blocking"]]

    def rate(rows):
        return f"{sum(r['overall_pass'] for r in rows)}/{len(rows)}" if rows else "0/0"

    print(f"\n{'='*60}")
    print(f"VERIFIED score   : {rate(verified)}")
    print(f"UNVERIFIED score : {rate(unverified)}  (measures self-consistency, not correctness)")
    print(f"BLOCKING score   : {rate(blocking)}  (any failure here fails the build)")
    print(f"{'='*60}")

    blocking_failed = [r["id"] for r in blocking if not r["overall_pass"]]
    if blocking_failed:
        print(f"BLOCKING FAILURES: {blocking_failed}")

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{stamp}_{prompts.PROMPT_VERSION}.json"
    out_path.write_text(json.dumps({
        "prompt_version": prompts.PROMPT_VERSION,
        "run_at": stamp,
        "verified_rate": rate(verified),
        "unverified_rate": rate(unverified),
        "blocking_rate": rate(blocking),
        "blocking_failures": blocking_failed,
        "results": results,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nresults written to {out_path}")

    return 1 if blocking_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
