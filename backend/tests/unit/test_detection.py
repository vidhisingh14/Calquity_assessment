"""Detection rules. Every rule exercised by a fixture (Phase 9 gate, per the
A7 resolution) rather than by requiring the real dataset to produce volume."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import detection

NOW = datetime(2026, 8, 16, 11, 0, tzinfo=timezone.utc)


def _ticket(id_, account, created_delta_min, severity="P2", issue_type="bulk_upload",
           status="open", subject="", description=""):
    return {"ticket_id": id_, "account_id": account,
            "created_at": NOW - timedelta(minutes=created_delta_min),
            "status": status, "derived_severity": severity,
            "derived_issue_type": issue_type, "subject": subject,
            "description": description}


def test_issue_spike_fires_at_three_in_24h_exceeding_baseline():
    tickets = [_ticket(f"T{i}", "ACCT-001", 60) for i in range(3)]
    tickets += [_ticket("T-old", "ACCT-001", 60 * 24 * 6, issue_type="bulk_upload")]
    signals = detection.issue_spike(tickets, NOW)
    assert len(signals) == 1
    assert signals[0]["signal_type"] == "issue_spike"


def test_issue_spike_silent_below_threshold():
    """This dataset's actual shape: max 1 ticket of any type in 24h."""
    tickets = [_ticket("T1", "ACCT-001", 60)]
    assert detection.issue_spike(tickets, NOW) == []


def test_sla_breached_fires_past_target():
    tickets = [_ticket("TKT-501", "ACCT-001", 30, severity="P1")]
    resolve = lambda acct, sev: 15  # 15-minute target, 30 elapsed
    signals = detection.sla_risk_and_breach(tickets, resolve, NOW)
    assert len(signals) == 1
    assert signals[0]["signal_type"] == "sla_breached"
    assert signals[0]["detail"]["breached_by_minutes"] == 15


def test_sla_risk_fires_within_two_hours_of_deadline():
    tickets = [_ticket("TKT-X", "ACCT-001", 100, severity="P2")]
    resolve = lambda acct, sev: 180  # 80 minutes remaining
    signals = detection.sla_risk_and_breach(tickets, resolve, NOW)
    assert signals[0]["signal_type"] == "sla_risk"


def test_sla_within_target_produces_no_signal():
    tickets = [_ticket("TKT-Y", "ACCT-001", 10, severity="P3")]
    resolve = lambda acct, sev: 500
    assert detection.sla_risk_and_breach(tickets, resolve, NOW) == []


def test_multi_account_issue_needs_three_accounts():
    tickets = [_ticket(f"T{i}", f"ACCT-00{i}", 60, issue_type="bulk_upload")
               for i in (1, 2, 3)]
    signals = detection.multi_account_issue(tickets)
    assert len(signals) == 1
    assert signals[0]["detail"]["account_count"] == 3


def test_multi_account_issue_silent_at_one_account():
    """The dataset's actual shape."""
    tickets = [_ticket("T1", "ACCT-001", 60, issue_type="bulk_upload")]
    assert detection.multi_account_issue(tickets) == []


def test_security_incident_matches_credential_language():
    tickets = [_ticket("TKT-505", "ACCT-004", 30, severity="P1",
                       subject="Possible API key exposure",
                       description="production API key posted publicly")]
    signals = detection.security_incident(tickets)
    assert len(signals) == 1
    assert signals[0]["severity"] == "urgent"


def test_security_incident_ignores_unrelated_tickets():
    tickets = [_ticket("TKT-1", "ACCT-001", 30, subject="How do I change my email")]
    assert detection.security_incident(tickets) == []


def test_known_issue_match_ki211():
    tickets = [_ticket("TKT-504", "ACCT-001", 10,
                       description="SwiftShip order still shows BOOKED after pickup")]
    signals = detection.known_issue_match(tickets)
    assert len(signals) == 1
    assert signals[0]["detail"]["known_issue"] == "KI-211"


def test_known_issue_match_ki208():
    tickets = [_ticket("TKT-502", "ACCT-002", 10,
                       description="Bulk upload fails for large CSV")]
    signals = detection.known_issue_match(tickets)
    assert signals[0]["detail"]["known_issue"] == "KI-208"


def test_unattended_p1_fires_past_window():
    tickets = [_ticket("TKT-501", "ACCT-001", 45, severity="P1")]
    signals = detection.unattended_p1(tickets, NOW)
    assert len(signals) == 1
    assert signals[0]["detail"]["elapsed_minutes"] == 45


def test_unattended_p1_silent_within_window():
    tickets = [_ticket("TKT-501", "ACCT-001", 10, severity="P1")]
    assert detection.unattended_p1(tickets, NOW) == []


def test_signal_id_is_deterministic_across_calls():
    """Re-runs must upsert, never duplicate."""
    tickets = [_ticket("TKT-505", "ACCT-004", 30, severity="P1",
                       subject="API key exposure")]
    a = detection.security_incident(tickets)[0]["signal_id"]
    b = detection.security_incident(tickets)[0]["signal_id"]
    assert a == b


def test_carrier_degradation_silent_without_enough_history():
    """Too few orders per carrier in this dataset for a baseline -- correctly
    produces nothing rather than a spurious signal from 6 data points."""
    orders = [{"order_id": f"O{i}", "account_id": "ACCT-001", "carrier": "SwiftShip",
              "pickup_actual_at": None, "pickup_window_end": None}
             for i in range(3)]
    assert detection.carrier_degradation(orders) == []
