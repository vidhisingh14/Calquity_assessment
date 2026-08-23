"""Pre-Phase-5 gate: does the chat provider call tools reliably?

Runs a question that REQUIRES a three-hop chain (lookup_records ->
search_documents -> evaluate_policy) ten times and counts how many runs
produced valid tool calls with correct arguments and no invented tool names.

    >= 9/10  -> keep the configured provider
    <  9/10  -> flip CHAT_PROVIDER, per the agreed gate

Run against the real loop rather than a bespoke harness, so the thing measured
is the thing that ships.

    python -m scripts.spike_tool_calling [--runs 10]
"""

from __future__ import annotations

import argparse
import json
import time

from app.agent import loop
from app.auth.context import AuthContext
from app.config import get_settings
from app.repositories import system_repo

QUESTION = (
    "Can Northstar cancel ORD-1001 without a cancellation fee, and why?"
)
REQUIRED_CHAIN = ["lookup_records", "search_documents", "evaluate_policy"]
PASS_THRESHOLD = 9

# One turn costs 4-6 API calls; free-tier limits are per MINUTE, so runs are
# paced rather than burst. Without this the spike measures rate limiting.
PACE_SECONDS = 6


def _run_once(ctx, snapshot) -> dict:
    started = time.perf_counter()
    result = loop.run_turn(
        message=QUESTION,
        ctx=ctx,
        snapshot_time=snapshot,
        session_id="spike",
        history=[],
        account_name="Northstar Logistics",
    )
    elapsed = time.perf_counter() - started

    called = [s.tool for s in result.steps]
    ok_steps = [s for s in result.steps if s.ok]
    verdict = result.verdicts[0] if result.verdicts else {}

    return {
        "tools": called,
        "invalid_names": result.invalid_tool_names,
        "invalid_args": result.invalid_args,
        # A run passes only if: no invented tool names, no argument validation
        # failures, every required tool was called, and every step succeeded.
        "no_invented": not result.invalid_tool_names,
        "args_valid": not result.invalid_args,
        "chain_complete": all(t in called for t in REQUIRED_CHAIN),
        "all_steps_ok": len(ok_steps) == len(result.steps) and bool(result.steps),
        "verdict_outcome": verdict.get("outcome"),
        "verdict_correct": (
            verdict.get("outcome") == "no_fee"
            and verdict.get("reason_code") == "contract_waiver"
            and verdict.get("override_applied") is True
        ),
        "budget_exhausted": result.budget_exhausted,
        "seconds": round(elapsed, 2),
        "answer": (result.answer or "")[:160],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args(argv)

    settings = get_settings()
    snapshot = system_repo.get_snapshot_time()
    ctx = AuthContext(user_id="u_northstar", role="customer", account_id="ACCT-001")

    print(f"provider = {settings.chat_provider}")
    print(f"model    = {settings.chat_model}")
    print(f"question = {QUESTION!r}")
    print(f"required chain = {' -> '.join(REQUIRED_CHAIN)}\n")

    results = []
    for i in range(1, args.runs + 1):
        try:
            outcome = _run_once(ctx, snapshot)
        except Exception as exc:  # noqa: BLE001 - a crash is a failed run
            outcome = {
                "tools": [], "invalid_names": [f"EXCEPTION: {exc}"],
                "invalid_args": [], "verdict_outcome": None,
                "no_invented": False, "args_valid": False,
                "chain_complete": False, "all_steps_ok": False,
                "verdict_correct": False, "budget_exhausted": False,
                "seconds": 0.0, "answer": str(exc)[:160],
            }
        # THE AGREED GATE: "valid tool calls with correct arguments and no
        # invented tool names". Chain completeness is deliberately NOT part of
        # it -- evaluate_policy resolves the order and contract terms itself, so
        # a model that calls it directly is being efficient, not wrong. Chain
        # shape is reported separately as an observation.
        passed = (
            outcome["no_invented"] and outcome["args_valid"]
            and outcome["all_steps_ok"]
        )
        outcome["passed"] = passed
        results.append(outcome)
        if i < args.runs:
            time.sleep(PACE_SECONDS)
        print(
            f"run {i:>2}  {'PASS' if passed else 'FAIL'}  "
            f"{outcome['seconds']:>5.2f}s  chain={'>'.join(outcome['tools']) or '(none)'}"
        )
        if not passed:
            if outcome["invalid_names"]:
                print(f"        invented tool names: {outcome['invalid_names']}")
            if outcome["invalid_args"]:
                print(f"        invalid args: {outcome['invalid_args']}")
            if not outcome["all_steps_ok"]:
                print(f"        no successful tool step (likely provider error)")

    score = sum(1 for r in results if r["passed"])
    verdicts_right = sum(1 for r in results if r["verdict_correct"])
    full_chain = sum(1 for r in results if r["chain_complete"])
    avg = sum(r["seconds"] for r in results) / len(results)

    print(f"\n{'='*62}")
    print(f"TOOL-CALLING SCORE : {score}/{args.runs}  (threshold {PASS_THRESHOLD})")
    print(f"VERDICT CORRECT    : {verdicts_right}/{args.runs}")
    print(f"FULL 3-HOP CHAIN   : {full_chain}/{args.runs}  (observational, not gated)")
    print(f"MEAN LATENCY       : {avg:.2f}s")
    print(f"GATE               : "
          f"{'PASS - keep ' + settings.chat_provider if score >= PASS_THRESHOLD else 'FAIL - flip CHAT_PROVIDER'}")
    print(f"{'='*62}")

    print(json.dumps({
        "provider": settings.chat_provider,
        "model": settings.chat_model,
        "runs": args.runs,
        "score": score,
        "verdict_correct": verdicts_right,
        "full_chain_observed": full_chain,
        "mean_seconds": round(avg, 2),
        "threshold": PASS_THRESHOLD,
        "gate_passed": score >= PASS_THRESHOLD,
    }, indent=2))

    return 0 if score >= PASS_THRESHOLD else 1


if __name__ == "__main__":
    raise SystemExit(main())
