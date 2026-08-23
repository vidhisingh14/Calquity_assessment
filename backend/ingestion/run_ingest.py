"""Ingestion entry point. Idempotent: truncates and reloads.

    python -m ingestion.run_ingest [--allow-empty-pages]

RUN ORDER IS NOT FILE-NUMBER ORDER, AND THAT IS DELIBERATE.

    06 -> 07 -> 01 -> 02 -> 03 -> 04 -> 05 -> 09 -> 08

The build spec numbers the workbook steps after the PDF steps, but step 3 has
to stamp each contract with a REAL account id resolved from the workbook. As
numbered, those ids do not exist yet. Filenames keep the spec's numbering so
the node map in section 5 still resolves; only the execution order is fixed.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.errors import IngestionError
from app.repositories import ingest_repo, system_repo
from app.services.classification import classify_ticket
from ingestion import (
    step_01_load_pdfs as s01,
    step_02_extract_text as s02,
    step_03_stamp_authority as s03,
    step_04_chunk as s04,
    step_05_embed_and_store as s05,
    step_06_load_workbook as s06,
    step_07_normalise as s07,
    step_08_assert as s08,
    step_09_load_terms as s09,
)


def _data_dir() -> pathlib.Path:
    return pathlib.Path(get_settings().data_dir).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ParcelPilot ingestion")
    parser.add_argument(
        "--allow-empty-pages",
        action="store_true",
        help="Continue past pages with no extractable text. OFF by default; "
             "skipped pages are recorded in system_meta and surfaced on /healthz. "
             "The deployed ingest path must never set this.",
    )
    args = parser.parse_args(argv)

    data_dir = _data_dir()
    raw_dir = data_dir / "raw"
    terms_path = data_dir / "terms_overrides.yaml"

    try:
        return _run(raw_dir, terms_path, allow_empty_pages=args.allow_empty_pages)
    except IngestionError as exc:
        print(f"\nINGESTION FAILED\n{exc}\n", file=sys.stderr)
        return 1


def _run(raw_dir: pathlib.Path, terms_path: pathlib.Path,
         allow_empty_pages: bool) -> int:
    print("== step 06: load workbook ==")
    workbook_path = raw_dir / "ParcelPilot_Assessment_Data.xlsx"
    sheets = s06.load_workbook(workbook_path)
    snapshot_raw = s06.extract_snapshot_raw(sheets["README"])
    snapshot = s07.parse_snapshot(snapshot_raw)
    tz = ZoneInfo(str(snapshot.tzinfo))
    print(f"   snapshot: {snapshot.isoformat()}  (from {snapshot_raw!r})")

    print("== step 07: normalise ==")
    ingest_repo.truncate_all()

    accounts = [
        {
            "account_id": s07.clean_id(r["account_id"]),
            "account_name": str(r["account_name"]).strip(),
            "plan": str(r["plan"]).strip(),
            "status": s07.normalise_lower(r["status"]),
            "csm": r.get("csm"),
            "premium_support": s07.to_bool(r.get("premium_support")) or False,
            "notes": r.get("notes"),
        }
        for r in sheets["accounts"]
    ]
    ingest_repo.insert_accounts(accounts)

    stamps: list[tuple[str, Any]] = []

    orders = []
    for r in sheets["orders"]:
        row = {
            "order_id": s07.clean_id(r["order_id"]),
            "account_id": s07.clean_id(r["account_id"]),
            "carrier": r.get("carrier"),
            "status": s07.normalise_status(r["status"]),
            "booked_at": s07.to_datetime(r.get("booked_at"), tz),
            "pickup_window_start": s07.to_datetime(r.get("pickup_window_start"), tz),
            "pickup_window_end": s07.to_datetime(r.get("pickup_window_end"), tz),
            "pickup_actual_at": s07.to_datetime(r.get("pickup_actual_at"), tz),
            "shipment_fee_inr": s07.to_decimal(r.get("shipment_fee_inr")),
            "carrier_fault": s07.to_bool(r.get("carrier_fault")),
            "customer_fault": s07.to_bool(r.get("customer_fault")),
            "cancellation_requested_at": s07.to_datetime(
                r.get("cancellation_requested_at"), tz
            ),
            "notes": r.get("notes"),
        }
        for field in ("booked_at", "pickup_window_start", "pickup_window_end",
                      "pickup_actual_at", "cancellation_requested_at"):
            if row[field] is not None:
                stamps.append((f"{row['order_id']}.{field}", row[field]))
        orders.append(row)
    ingest_repo.insert_orders(orders)

    tickets = []
    for r in sheets["tickets"]:
        classification = classify_ticket(r.get("subject"), r.get("description"))
        row = {
            "ticket_id": s07.clean_id(r["ticket_id"]),
            "account_id": s07.clean_id(r["account_id"]),
            "created_at": s07.to_datetime(r.get("created_at"), tz),
            "status": s07.normalise_lower(r.get("status")),
            "subject": r.get("subject"),
            "description": r.get("description"),
            "channel": s07.normalise_lower(r.get("channel")),
            "assigned_to": r.get("assigned_to"),
            "last_customer_message_at": s07.to_datetime(
                r.get("last_customer_message_at"), tz
            ),
            "historical_resolution": r.get("historical_resolution"),
            "derived_severity": classification.severity,
            "severity_rationale": classification.rationale,
            "derived_issue_type": classification.issue_type,
        }
        for field in ("created_at", "last_customer_message_at"):
            if row[field] is not None:
                stamps.append((f"{row['ticket_id']}.{field}", row[field]))
        tickets.append(row)
    ingest_repo.insert_tickets(tickets)

    # The two assertions that catch the timestamp hazards. See step_07's docstring.
    s07.assert_all_aware(stamps)
    s07.assert_within_window(stamps, snapshot)
    system_repo.set_meta(system_repo.SNAPSHOT_KEY, snapshot.isoformat())
    print(f"   accounts={len(accounts)} orders={len(orders)} tickets={len(tickets)}")

    print("== step 01: load PDFs ==")
    pdfs = s01.load_pdfs(raw_dir)

    embedder = _get_embedder()
    doc_meta: dict[str, dict[str, Any]] = {}
    chunks_by_doc: dict[str, list[tuple[int, str]]] = {}
    all_skipped: dict[str, list[int]] = {}
    supersedes: list[tuple[str, str]] = []

    for path in pdfs:
        print(f"== steps 02-05: {path.name} ==")
        extracted = s02.extract_text(path, allow_empty_pages=allow_empty_pages)
        if extracted.skipped_pages:
            all_skipped[path.name] = extracted.skipped_pages

        meta = s03.stamp(path.name, accounts)
        pending_supersede = meta.pop("superseded_by", None)
        ingest_repo.insert_document(dict(meta, superseded_by=None))
        if pending_supersede:
            supersedes.append((meta["doc_id"], pending_supersede))
        doc_meta[meta["doc_id"]] = meta

        if meta.get("account_scope"):
            ingest_repo.link_account_contract(meta["account_scope"], meta["doc_id"])

        chunks = s04.chunk_document(meta, extracted.pages)
        chunk_ids = s05.embed_and_store(chunks, embedder)
        chunks_by_doc[meta["doc_id"]] = list(zip(chunk_ids, [c.content for c in chunks]))
        print(f"   pages={extracted.page_count} chunks={len(chunks)} tier={meta['authority_tier']}")

    # Applied after all documents exist, so the FK always resolves.
    for doc_id, target in supersedes:
        ingest_repo.set_superseded_by(doc_id, target)

    if all_skipped:
        rendered = "; ".join(f"{k}:{v}" for k, v in all_skipped.items())
        system_repo.set_meta(system_repo.SKIPPED_PAGES_KEY, rendered)
        print(f"   WARNING skipped empty pages -> {rendered}")
    else:
        system_repo.set_meta(system_repo.SKIPPED_PAGES_KEY, "none")

    print("== step 09: verify declared terms ==")
    terms_result = s09.load_terms(terms_path, chunks_by_doc, doc_meta)
    print(f"   loaded={terms_result['loaded']} "
          f"verified={terms_result['verified']} "
          f"unverified={terms_result['unverified']}")

    print("== step 08: assertions ==")
    summary = s08.run_assertions()
    s08.print_summary(summary)

    if summary.get("terms_unverified"):
        print(
            f"\n  NOTE {summary['terms_unverified']} policy term(s) are still "
            f"unverified (drafted, not human-signed-off). Eval reports verified "
            f"and unverified scores separately.\n"
        )

    print("ingestion complete")
    return 0


def _get_embedder():
    from app.llm.embeddings import get_embedder

    return get_embedder()


if __name__ == "__main__":
    raise SystemExit(main())
