"""Scheduled job: run detection rules, write signals, name them with one LLM call.

    python -m jobs.detect_signals

Run via cron / APScheduler / a Render cron job. Idempotent: signal_id is
deterministic, so re-runs upsert the same open signal rather than duplicating.
"""

from __future__ import annotations

from app.repositories import signals_repo, system_repo, terms_repo
from app.services import detection, terms as terms_service


def _target_resolver():
    """Adapter: resolve_target(account_id, severity) -> minutes, using the
    same term resolution the policy engine uses, so the board and the chat
    agent can never disagree about what a target is."""
    from app.repositories import accounts_repo

    cache: dict[str, terms_service.TermSet] = {}

    def resolve(account_id: str, severity: str) -> int | None:
        if account_id not in cache:
            account = accounts_repo.get_account(account_id, None)
            cache[account_id] = terms_service.load(account, account_id)
        try:
            target = cache[account_id].resolve_sla_target(severity)
        except Exception:  # noqa: BLE001 - undecidable just means no signal
            return None
        unit_minutes = {"minutes": 1, "hours": 60, "business_hours": 60,
                        "business_days": 540}.get(target.unit or "minutes", 1)
        return int(float(target.value) * unit_minutes)

    return resolve


def _name_signal(signal: dict) -> tuple[str, str]:
    """One LLM call per signal for a human title and suggested next action.

    Deliberately the ONLY model-touched step. If this call fails, the signal
    still gets written with its rule-generated title -- naming is cosmetic,
    detection is not.
    """
    try:
        from app.llm.client import get_judge_client

        client = get_judge_client()
        prompt = (
            f"Write a one-line human-readable title (max 12 words) and a "
            f"one-sentence suggested next action for this operational signal. "
            f"Type: {signal['signal_type']}. Detail: {signal['detail']}. "
            f"Respond as JSON: {{\"title\": ..., \"action\": ...}}"
        )
        resp = client.complete(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": {"schema": {
                "type": "object",
                "properties": {"title": {"type": "string"},
                               "action": {"type": "string"}},
                "required": ["title", "action"],
            }}},
        )
        import json

        data = json.loads(resp.content or "{}")
        return data.get("title") or signal["title"], data.get("action", "")
    except Exception:  # noqa: BLE001 - naming is cosmetic
        return signal["title"], ""


def main() -> int:
    snapshot = system_repo.get_snapshot_time()
    tickets = signals_repo.snapshot_open_tickets()
    orders = signals_repo.snapshot_orders()

    signals = detection.detect_all(tickets, orders, _target_resolver(), snapshot)

    print(f"snapshot_time = {snapshot.isoformat()}")
    print(f"tickets scanned = {len(tickets)}  orders scanned = {len(orders)}")
    print(f"signals detected = {len(signals)}\n")

    for signal in signals:
        title, action = _name_signal(signal)
        signal["title"] = title
        if action:
            signal["detail"]["suggested_action"] = action
        signals_repo.upsert(signal)
        print(f"  [{signal['severity']:6}] {signal['signal_type']:20} {title}")

    if not signals:
        print("  (none -- see design doc assumption A7 on why this dataset "
              "does not reach most §12 thresholds)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
