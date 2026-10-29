# Evaluation protocol

The evaluation unit is an expected feed occurrence, keyed by feed, partner and
scheduled local date. Predictions and labels are sets over MISSING_FILE,
LATE_FILE, MISSING_ACK and LATE_ACK. An empty set denotes no finding at the
specified as-of instant. The evaluator rejects mismatched occurrence-key sets.

Exact match is the fraction of occurrences with exactly the correct finding set.
Per-class precision=TP/(TP+FP), recall=TP/(TP+FN), F1=2TP/(2TP+FP+FN).
Micro metrics pool TP/FP/FN over all four classes. Undefined metrics are JSON null.
True negatives are not included in F1. Results are synthetic point scores, with
no confidence intervals, significance claims or measured production impact.

## Methods

1. `etm`: reference monitor with successful transfer and business-ACK correlation.
2. `transfer_only`: same transfer monitoring, dropping ACK findings (an ablation).
3. `uncorrelated_receipt`: same transfer monitoring, accepting any successful
   business ACK or transport receipt in the occurrence, without reference matching
   or ACK-after-transfer validation.

These intentionally simple baselines isolate the value of configured ACK checks.
They are not implementations of Sterling, Axway, commercial monitoring products,
or state-of-the-art research. Shared transfer logic means they are not independent
implementations. This comparison cannot establish superiority over those systems.

The generator never calls the monitor to obtain labels, but the benchmark remains
hand-constructed around the specification. A perfect score is a conformance result.
Run `verify.py` to regenerate in a temporary directory and compare all dataset files
and the result report byte for byte. Simulator and evaluator CLIs support other
seeds; evaluating additional seeds is a robustness exercise, not external validation.

## Cost and next research steps

The prototype scans events per job and may compare multiple transfers per ACK.
It is deliberately simple, not optimized for large workloads. No throughput or
latency claim is made. Future work includes indexed event lookup, ingestion-time
modeling, independently reviewed cases, legitimate external datasets and adapter
implementations. Schedule learning would require a separate experimental protocol.
