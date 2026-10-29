# ETM synthetic benchmark v1.0.0

## Provenance and intended use

Generated entirely by `simulate.py`, generator version 1.0.0, default seed 42.
No real organizations, people, production logs, payroll, or encrypted payloads
were used. Intended for reproducibility, interoperability and conformance checks,
not training or validating a learned model. License: MIT (repository LICENSE).

## Composition

420 independent feed occurrences, 30 per scenario. Every feed has one expected
occurrence on Monday 2026-01-05, 08:00 UTC, a five-hour file grace period, and a
Wednesday 17:00 UTC business-ACK deadline. Observation ends Thursday 00:00 UTC,
after all generated events. Event rows are shuffled; duplicates are intentional.
Counts and generation parameters are recorded in `v1/metadata.json`.

Scenarios: on_time, missing_file, failed_only, late_file, missing_ack, late_ack,
receipt_only, wrong_reference, wrong_partner, ack_before_transfer, retry_success,
duplicate_events, deadline_exact, late_both. Labels are scenario-defined lists of
findings, created without invoking or importing the reference monitor. Each row
is identified by feed, partner and occurrence. The scenario name is diagnostic
metadata, not a detector input feature; feed names also reveal scenarios, so
this dataset MUST NOT be used to claim learned-model generalization.

## Files

- `manifest.json`: feed obligations conforming to manifest spec 1.0.
- `events.jsonl`: synthetic metadata events; no payload fields.
- `labels.json`: one ground-truth findings list and scenario per occurrence.
- `metadata.json`: version, seed, repetition count, date range and as-of instant.
- `SHA256SUMS`: hashes of the four files above.
- `../results.json`: reproducible evaluation report.

## Limitations

Balanced engineered cases do not represent operational prevalence. No train/test
split is provided because no learning is performed. Scenario templates and rules
were designed together, so perfect reference scores are expected and are not
independent scientific validation. Repetition varies timestamps only; it does not
create 420 distinct failure mechanisms. UTC benchmark cases do not exercise DST;
unit tests separately check timezone behavior. No corrupted log collection,
watermarks, delayed ingestion, holiday calendars, sustained load, ambiguous
occurrence assignment, or real business-level correctness is represented.
Synthetic ACK success is stipulated, not inferred from file contents.

## Extending responsibly

Add explicit scenario labels before changing the monitor, retain failing cases,
bump the dataset version if content/semantics change, and publish seeds and hashes.
A separate independently sourced evaluation is needed for real-world claims.
