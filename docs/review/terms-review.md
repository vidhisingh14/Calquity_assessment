# Policy terms — review table

**Status: every row is `unverified: true` until you sign it off.**

I drafted all of these from one reading of the PDFs. That is exactly the
self-consistency risk you named, so nothing here counts as verified until you say
so. Sign-off is per row — strike, correct, or tick each one.

**How `source_chunk_id` gets bound.** Chunk ids are assigned by `BIGSERIAL` at
ingest, so the YAML cannot name them up front. Instead each term declares
`source_quote`. Ingestion locates the chunk containing that quote **literally**,
binds its `chunk_id` into `doc_terms.source_chunk_id`, and **fails the ingest** if
the quote is not found verbatim. So a wrong quote below breaks the build rather
than silently producing a wrong answer.

Column **R** marks rows the three `evaluate_policy` rules depend on directly.
Rows without R are context the agent may cite but no arithmetic uses.
Row **23** is marked **✎**: it is documentation only and is deliberately *not*
loaded into `doc_terms`, because the authority ladder is already implemented once
in `documents.authority_tier` (§6.1 — "define it once, never re-implement it").
That is why the YAML holds 47 terms against this table's 48 rows.

---

## `sop_v4` — Cancellation & Service Credit SOP v4 (tier 3)

| # | R | term_key | value | unit | Literal source sentence |
|---|---|---|---|---|---|
| 1 | ● | `cancellation.draft_fee_inr` | 0 | INR | "DRAFT: May be cancelled with no fee." |
| 2 | ● | `cancellation.free_window_minutes` | 30 | minutes | "No fee within 30 minutes of booking." |
| 3 | ● | `cancellation.fee_after_window_inr` | 250 | INR | "After 30 minutes, charge INR 250 unless a customer agreement explicitly waives the cancellation fee." |
| 4 | ● | `cancellation.waivable_by_agreement` | true | bool | "…unless a customer agreement explicitly waives the cancellation fee." |
| 5 | ● | `cancellation.picked_up_allowed` | false | bool | "PICKED_UP: Do not cancel. Use the return-to-origin workflow if the customer wants the parcel returned." |
| 6 | ● | `cancellation.delivered_allowed` | false | bool | "DELIVERED: Cannot be cancelled." |
| 7 | ● | `service_credit.delay_threshold_hours` | 2 | hours | "…the pickup is more than 2 hours past the end of the scheduled pickup window…" |
| 8 | ● | `service_credit.requires_carrier_fault` | true | bool | "…the carrier is at fault, and there is no customer-caused issue." |
| 9 | ● | `service_credit.requires_no_customer_fault` | true | bool | "…and there is no customer-caused issue." |
| 10 | ● | `service_credit.amount_cap_inr` | 500 | INR | "The default credit is the lower of INR 500 or 10% of the shipment fee." |
| 11 | ● | `service_credit.amount_pct_of_fee` | 10 | percent | "The default credit is the lower of INR 500 or 10% of the shipment fee." |
| 12 | ● | `service_credit.manager_approval_above_inr` | 1000 | INR | "Any individual credit above INR 1,000 requires manager approval." |
| 13 | ● | `service_credit.undecidable_when_facts_unknown` | true | bool | "Do not promise a credit when carrier fault, pickup timing, or customer fault is unknown." |

## `policy_v3` — Support Policy v3, CURRENT (tier 2)

First-response targets. Term key pattern `sla.first_response.{plan}.{severity}`.

| # | R | term_key | value | unit | Literal source sentence |
|---|---|---|---|---|---|
| 14 | ● | `sla.first_response.Enterprise.P1` | 30 | minutes (24x7) | "Enterprise 30 minutes, 24x7 2 hours 1 business day" |
| 15 | ● | `sla.first_response.Enterprise.P2` | 2 | hours | "Enterprise 30 minutes, 24x7 2 hours 1 business day" |
| 16 | ● | `sla.first_response.Enterprise.P3` | 1 | business_days | "Enterprise 30 minutes, 24x7 2 hours 1 business day" |
| 17 | ● | `sla.first_response.Growth.P1` | 2 | business_hours | "Growth 2 business hours 4 business hours 2 business days" |
| 18 | ● | `sla.first_response.Growth.P2` | 4 | business_hours | "Growth 2 business hours 4 business hours 2 business days" |
| 19 | ● | `sla.first_response.Growth.P3` | 2 | business_days | "Growth 2 business hours 4 business hours 2 business days" |
| 20 | ● | `sla.first_response.Standard.P1` | 4 | business_hours | "Standard 4 business hours 1 business day 2 business days" |
| 21 | ● | `sla.first_response.Standard.P2` | 1 | business_days | "Standard 4 business hours 1 business day 2 business days" |
| 22 | ● | `sla.first_response.Standard.P3` | 2 | business_days | "Standard 4 business hours 1 business day 2 business days" |
| 23 | ✎ | `precedence.order` | agreement > policy > product_docs | ordering | "When sources conflict, use the signed customer agreement first, then the current support policy, then current product documentation." |
| 24 | | `precedence.tickets_context_only` | true | bool | "Historical tickets and internal notes are context only and may contain incorrect past guidance." |

**Note on rows 14–22:** the source "sentence" is a table row, which pdfplumber
flattens into one line. The value-in-chunk check still passes because the numbers
appear literally in that line, but the mapping of column position to severity is
**my reading of the table layout**, not something the text states. This is the
single most error-prone block in the file — worth your closest look.

## `contract_northstar` — Northstar Enterprise Agreement (tier 1, ACCT-001)

| # | R | term_key | value | unit | Literal source sentence |
|---|---|---|---|---|---|
| 25 | ● | `sla.first_response.P1` | 15 | minutes (24x7) | "P1: 15 minutes, 24x7" |
| 26 | ● | `sla.first_response.P2` | 1 | hours | "P2: 1 hour" |
| 27 | ● | `sla.first_response.P3` | 8 | business_hours | "P3: 8 business hours" |
| 28 | ● | `cancellation.fee_waived` | true | bool | "Northstar may cancel any BOOKED shipment before pickup with no cancellation fee, regardless of how long ago the shipment was booked." |
| 29 | ● | `cancellation.fee_waived_ignores_window` | true | bool | "…regardless of how long ago the shipment was booked." |
| 30 | ● | `cancellation.picked_up_allowed` | false | bool | "Once a shipment is PICKED_UP, the standard return-to-origin process applies." |
| 31 | | `service_credit.monthly_aggregate_cap_inr` | 5000 | INR | "Monthly aggregate service credits are capped at INR 5,000." |
| 32 | ● | `service_credit.defers_to_sop` | true | bool | "Unless this agreement states otherwise, the current ParcelPilot service-credit SOP applies." |

**Row 31 is stated but not enforceable** — see assumption A10. No credits ledger
exists, so remaining headroom is unknowable.

## `contract_lumenworks` — LumenWorks Service Agreement (tier 1, ACCT-002)

| # | R | term_key | value | unit | Literal source sentence |
|---|---|---|---|---|---|
| 33 | ● | `sla.first_response.P1` | 2 | business_hours | "P1: 2 business hours" |
| 34 | ● | `sla.first_response.P2` | 4 | business_hours | "P2: 4 business hours" |
| 35 | ● | `sla.first_response.P3` | 2 | business_days | "P3: 2 business days" |
| 36 | | `sla.coverage.weekend_or_after_hours` | false | bool | "No weekend or after-hours support coverage." |
| 37 | ● | `cancellation.defers_to_sop` | true | bool | "No special cancellation-fee waiver applies. Use the current ParcelPilot Cancellation & Service Credit SOP." |
| 38 | ● | `service_credit.delay_threshold_hours` | 4 | hours | "If a pickup is more than 4 hours past the end of the scheduled pickup window…" |
| 39 | ● | `service_credit.fixed_amount_inr` | 300 | INR | "…LumenWorks receives a fixed INR 300 service credit." |
| 40 | ● | `service_credit.replaces_sop_amount_and_threshold` | true | bool | "This clause replaces the default failed-pickup credit amount and timing threshold in the SOP." |

## `product_guide` — Product Operations Guide (tier 3)

| # | R | term_key | value | unit | Literal source sentence |
|---|---|---|---|---|---|
| 41 | | `bulk_upload.max_rows` | 5000 | rows | "Bulk Upload: Available on Growth and Enterprise. Supported file size is up to 5,000 rows per CSV." |
| 42 | | `bulk_upload.available_plans` | Growth, Enterprise | list | "Bulk Upload: Available on Growth and Enterprise." |
| 43 | | `bulk_upload.excluded_plans` | Standard | list | "Standard: Bulk Upload is not included." |
| 44 | | `known_issue.KI-208.failure_threshold_rows` | 3000 | rows | "Some Growth and Enterprise customers experience intermittent failures on CSV uploads above approximately 3,000 rows, even though the supported product limit remains 5,000 rows." |
| 45 | | `known_issue.KI-211.max_webhook_delay_minutes` | 20 | minutes | "SwiftShip pickup confirmation webhooks can arrive up to 20 minutes late." |

## `policy_v2` — Support Policy v2, DEPRECATED (tier 5)

Extracted **only** so tests can assert these values never appear in a customer
answer. The policy engine must never select a tier-5 term.

| # | R | term_key | value | unit | Literal source sentence |
|---|---|---|---|---|---|
| 46 | | `sla.first_response.Enterprise.P1` | 1 | hours | "Enterprise 1 hour 4 hours 2 business days" |
| 47 | | `sla.first_response.Growth.P1` | 4 | business_hours | "Growth 4 business hours 1 business day 3 business days" |
| 48 | | `sla.first_response.Standard.P1` | 8 | business_hours | "Standard 8 business hours 2 business days 3 business days" |

---

## Ambiguities in this file that I did not resolve

1. **Rows 14–22 column mapping** (above). The severity-to-column mapping is inferred from table layout.
2. **Row 2 vs assumption A1.** "Within 30 minutes of booking" — measured to *what* end point? I propose `cancellation_requested_at`, falling back to snapshot time. The SOP does not say.
3. **Rows 25–27 vs 14–16.** Northstar's contract replaces the *targets* but says nothing about whether "24x7" carries to P2 and P3. Policy v3 marks only Enterprise P1 as 24x7. I have assumed Northstar P2's "1 hour" is also 24x7 (the clause says these "replace ParcelPilot's standard targets" wholesale) but P3's "8 business hours" is explicitly business-hours. **This is a genuine gap in the wording.**
4. **Row 32 vs row 38.** Northstar defers to the SOP for credits; LumenWorks replaces it. So a Northstar credit uses SOP's 2-hour threshold and lower-of-500-or-10% formula, while LumenWorks uses 4 hours and flat 300. I am confident in this reading, but it is the single distinction that makes several golden questions differ, so it is worth a deliberate look.
5. **Row 36.** "No weekend or after-hours support coverage" could mean either that the clock pauses outside business hours, or that support simply is unavailable. I have implemented it as the clock pausing. The contract does not say.
