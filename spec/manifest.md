# Expected Transfer Manifest (ETM), version 1.0

Status: experimental project specification, not an industry standard.
The normative words MUST and MUST NOT describe this project's contract only.

## Purpose

Describe expected file-transfer occurrences and associated business acknowledgments
without access to payload contents. A transport receipt MUST NOT satisfy a business
ACK requirement. A successful business ACK means a configured business milestone,
not simply receipt of an ACK file. The source adapter is responsible for this mapping.

## Manifest fields

See `manifest.schema.json` for the machine-readable JSON Schema (draft 2020-12).

| Field | Meaning |
|---|---|
| `spec_version` | MUST be `1.0` |
| `feeds[].id` | Nonempty globally unique feed identifier within the manifest |
| `partner_id` | Nonempty partner identifier |
| `timezone` | IANA timezone, e.g. `America/Los_Angeles` |
| `schedule.kind` | `weekly` or `nth_weekday` |
| `schedule.weekday` | Integer: Monday=0 through Sunday=6 |
| `schedule.nth` | Required for `nth_weekday`: integer 1–5 |
| `schedule.time` | Local time, HH:MM, using a 24-hour clock |
| `grace_minutes` | Nonnegative integer elapsed minutes after the scheduled instant |
| `ack.days_after` | Nonnegative integer local calendar days after the scheduled date |
| `ack.time` | Local HH:MM on that calendar date |

Weekly feeds occur on every matching weekday in the requested inclusive date range.
A nonexistent fifth weekday creates no occurrence. Holidays/business days are not modeled.
The reference implementation rejects nonexistent or ambiguous DST schedule/deadline times.
Grace is elapsed UTC time; ACK dates use local calendar arithmetic.
An ACK deadline MUST NOT precede the file deadline. Duplicate feed IDs are invalid.
These semantic constraints cannot all be expressed in JSON Schema.

## Event contract

Each JSONL record contains `id`, `feed_id`, `partner_id`, `occurrence_id`, `kind`,
`status`, and `timestamp`, all nonempty strings. `occurrence_id` is the scheduled
local date YYYY-MM-DD, not necessarily the event date. `timestamp` is an ISO 8601
instant with explicit UTC offset (or Z). `kind` is `transfer`, `transport_receipt`,
or `business_ack`. `status` is `success` or `failed`.
Transfers MUST include nonempty string `transfer_id`; business ACKs MUST include
nonempty string `ack_ref`. No filenames, payloads or secrets are required.
Adapters MUST assign occurrence identity authoritatively, rather than guess from
an ambiguous filename. Transfer references MUST identify the intended attempt
within a feed/partner/occurrence; reference reuse across distinct attempts is unsupported.

## Correlation and deadlines

The occurrence key is `(feed_id, partner_id, occurrence_id)`.
Only successful transfers satisfy delivery. An ACK qualifies only when it matches
the occurrence key and its `ack_ref` equals a successful transfer's `transfer_id`,
and its timestamp is at or after that transfer. A failed attempt's ACK cannot
satisfy a successful retry. Earliest qualifying successful transfer and ACK times
are used. Retries may have different transfer IDs.

Events after the as-of instant are excluded. Identical event IDs with identical
records are deduplicated. Conflicting records sharing an ID invalidate the input.
Event input order has no semantic effect. Unmatched events are ignored; this
prototype does not diagnose orphan events or measure log ingestion reliability.

At a deadline, a recorded qualifying event at exactly that instant is on time;
otherwise the obligation is overdue. Before the deadline it is waiting.
Missing transfer yields `MISSING_FILE`, suppressing redundant `MISSING_ACK`.
A recovered late transfer yields `LATE_FILE`; absent/late ACKs can add
`MISSING_ACK`/`LATE_ACK`. Late findings persist after recovery. This is event-time
snapshot evaluation, not a real-time delivery guarantee or an ingestion-time model.

## Output

One row per occurrence contains keys, scheduled time, file and ACK deadlines,
state, findings, selected event IDs and an explanation. States are `waiting_file`,
`missing_file`, `waiting_ack`, `missing_ack`, `complete`, or `complete_late`.
`findings` is authoritative for lateness; e.g. waiting_ack can also have LATE_FILE.

## Compatibility

Version 1.0 is intentionally small: no schedule learning, business calendars,
streaming watermark policy, dynamic feed discovery, cryptographic validation or
payload reconciliation. Adding incompatible fields or changing deadline semantics
requires a new spec version. Existing source adapters are not supplied.
