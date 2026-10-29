"""Reference prototype and synthetic evaluation for expected transfer manifests (ETM).

Generates synthetic MFT/EDI transfer-metadata logs, learns a manifest per feed from a
training period, reconciles a test period with injected faults, and compares against
a static-rule baseline. Metadata only: no payloads are generated or read.
"""
import random, statistics, time, json, hashlib, sys
from datetime import datetime, timedelta, date, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict, Counter

SEED = 20261017
UTC = timezone.utc
TRAIN_START, TRAIN_END = date(2026, 1, 5), date(2026, 3, 1)    # 8 weeks history
TEST_START, TEST_END = date(2026, 3, 2), date(2026, 6, 28)     # 17 weeks, spans US/UK DST
HOLIDAYS = {date(2026, 1, 19), date(2026, 2, 16), date(2026, 5, 25)}  # US business calendar
TZS = ["America/Los_Angeles", "America/Chicago", "America/New_York", "Europe/London", "Asia/Kolkata"]
NRT_GRACE = timedelta(minutes=15)
BATCH_GRACE = timedelta(hours=5)


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def make_feeds(rng):
    feeds = []
    for i in range(60):
        kind = "weekly" if i < 25 else ("daily" if i < 50 else "nrt")
        f = {"id": f"F{i:02d}", "partner": f"TP-{i:02d}", "tz": rng.choice(TZS), "kind": kind,
             "calendar": rng.random() < 0.7, "size_mu": rng.uniform(2e5, 5e7)}
        if kind == "weekly":
            f["days"] = {rng.randrange(5)}
            f["hour"], f["minute"] = rng.randrange(5, 12), rng.choice([0, 15, 30, 45])
            f["ack_lag_h"] = rng.choice([4, 24, 48])
        elif kind == "daily":
            f["days"] = {0, 1, 2, 3, 4}
            f["hour"], f["minute"] = rng.randrange(1, 10), rng.choice([0, 30])
            f["ack_lag_h"] = rng.choice([1, 2, 6])
        else:  # near-real-time: hourly 08:00-17:00 on business days
            f["days"] = {0, 1, 2, 3, 4}
            f["hours"] = list(range(8, 18))
            f["minute"] = rng.choice([5, 20, 35])
            f["ack_lag_h"] = 0.25
        f["has_ack"] = rng.random() < 0.8
        feeds.append(f)
    return feeds


def occurrences(f, d0, d1, days=None):
    """True schedule occurrences (local wall-clock) for a feed in [d0, d1]."""
    days = f["days"] if days is None else days
    tz = ZoneInfo(f["tz"])
    for d in daterange(d0, d1):
        if d.weekday() not in days or (f["calendar"] and d in HOLIDAYS):
            continue
        for h in (f["hours"] if f["kind"] == "nrt" else [f["hour"]]):
            yield datetime(d.year, d.month, d.day, h, f["minute"], tzinfo=tz)


def checksum(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def jitter(rng, f):
    return timedelta(minutes=rng.uniform(0, 4) if f["kind"] == "nrt" else rng.uniform(0, 25))


def gen_period(rng, feeds, d0, d1, faults=None):
    """Return (events, ground truth list). faults: dict of occurrence-level injections."""
    ev, truth = [], []
    for f in feeds:
        sched_days = f["days"]
        for occ in occurrences(f, d0, d1, sched_days):
            key = (f["id"], occ.isoformat())
            fault = (faults or {}).get(key)
            t = (occ + jitter(rng, f)).astimezone(UTC)
            size = max(1000, int(rng.gauss(f["size_mu"], f["size_mu"] * 0.08)))
            ck = checksum(f"{key}{rng.random()}")
            truth.append((f["id"], occ, fault))
            if fault == "missing_send":
                continue
            if fault == "retry":
                ev.append({"feed": f["id"], "kind": "send", "t": t, "status": "failed", "size": size, "ck": ck})
                t = t + timedelta(minutes=10)
            if fault == "partial":
                size = int(size * 0.1)
            ev.append({"feed": f["id"], "kind": "send", "t": t, "status": "ok", "size": size, "ck": ck})
            if fault == "duplicate":
                ev.append({"feed": f["id"], "kind": "send", "t": t + timedelta(minutes=5 if f["kind"] == "nrt" else 45), "status": "ok", "size": size, "ck": ck})
            if f["has_ack"] and fault != "missing_ack":
                lag = timedelta(hours=f["ack_lag_h"]) * rng.uniform(0.5, 1.0)
                if fault == "late_ack":
                    lag = timedelta(hours=f["ack_lag_h"]) * 3 + timedelta(hours=6)
                ev.append({"feed": f["id"], "kind": "ack", "t": t + lag, "status": "ok", "ref": key[1]})
    return ev, truth


# ---------------- manifest learning ----------------
def learn_manifests(feeds, events, d0, d1):
    by = defaultdict(lambda: {"send": [], "ack": []})
    for e in events:
        if e["status"] == "ok":
            by[e["feed"]][e["kind"]].append(e)
    weeks = ((d1 - d0).days + 1) / 7
    mans = {}
    for f in feeds:
        tz = ZoneInfo(f["tz"])
        sends = sorted(by[f["id"]]["send"], key=lambda e: e["t"])
        local = [e["t"].astimezone(tz) for e in sends]
        wd = Counter(l.weekday() for l in local)
        # weekday recurs if seen in at least 60% of weeks
        days = {d for d, c in wd.items() if c / weeks >= 0.6 if f["kind"] != "nrt"} or set(wd)
        if f["kind"] == "nrt":
            days = {d for d, c in wd.items() if c / (weeks * 10) >= 0.6}
            hours = sorted({l.hour for l in local if Counter(x.hour for x in local)[l.hour] / (weeks * len(days)) >= 0.6})
            minute = int(statistics.median(l.minute for l in local))
            grace = NRT_GRACE
        else:
            hours = [int(statistics.median(l.hour for l in local))]
            minute = int(statistics.median((l.hour * 60 + l.minute) for l in local)) % 60
            grace = BATCH_GRACE
        sizes = sorted(e["size"] for e in sends)
        q = lambda p: sizes[min(len(sizes) - 1, int(p * len(sizes)))]
        ack_window = None
        if by[f["id"]]["ack"]:
            # ack due = p95 of observed lag x 1.5
            sm = {e["t"].astimezone(tz).date(): e["t"] for e in sends}
            lags = sorted((a["t"] - sm[datetime.fromisoformat(a["ref"]).date()]).total_seconds()
                          for a in by[f["id"]]["ack"] if datetime.fromisoformat(a["ref"]).date() in sm)
            ack_window = timedelta(seconds=lags[int(0.95 * (len(lags) - 1))] * 1.5)
        mans[f["id"]] = {"tz": f["tz"], "days": days, "hours": hours, "minute": minute, "grace": grace,
                         "calendar": f["calendar"], "size": (q(0.05), q(0.95)), "ack": ack_window,
                         "nrt": f["kind"] == "nrt"}
    return mans


def expected(man, d0, d1):
    tz = ZoneInfo(man["tz"])
    for d in daterange(d0, d1):
        if d.weekday() not in man["days"] or (man["calendar"] and d in HOLIDAYS):
            continue
        for h in man["hours"]:
            yield datetime(d.year, d.month, d.day, h, man["minute"], tzinfo=tz)


# ---------------- reconciliation ----------------
def reconcile(mans, events, d0, d1, outages):
    """Match expected occurrences against observed metadata; O((E + X) log E) per run."""
    from bisect import bisect_left, bisect_right
    alerts = []
    by = defaultdict(list)
    acks = defaultdict(list)
    for e in events:
        (acks if e["kind"] == "ack" else by)[e["feed"]].append(e)
    for v in list(by.values()) + list(acks.values()):
        v.sort(key=lambda e: e["t"])
    def in_outage(a, b):
        return any(s < b and a < e for s, e in outages)
    for fid, m in mans.items():
        sends, seen, dups = [], {}, []
        for e in by[fid]:
            if e["status"] != "ok":
                continue  # failed attempts are superseded by the retry
            if e["ck"] in seen:
                dups.append((seen[e["ck"]], e))  # identical checksum already received
                continue
            seen[e["ck"]] = e
            sends.append(e)
        st = [e["t"] for e in sends]
        at = [a["t"] for a in acks[fid]]
        used = set()
        early = timedelta(minutes=10) if m["nrt"] else timedelta(hours=2)
        occ_of = {}
        for occ in expected(m, d0, d1):
            lo, hi = occ - early, occ + m["grace"]
            match = [i for i in range(bisect_left(st, lo), bisect_right(st, hi)) if i not in used]
            if not match:
                kind = "monitoring_gap" if in_outage(lo, hi) else "missing_delivery"
                alerts.append((fid, occ, kind, hi))
                continue
            first = sends[match[0]]
            used.update(match)
            for i in match:
                occ_of[id(sends[i])] = occ
            if first["size"] < m["size"][0] * 0.5 or first["size"] > m["size"][1] * 2:
                alerts.append((fid, occ, "partial_delivery", first["t"]))
            if m["ack"] is not None:
                due = first["t"] + m["ack"] + (m["grace"] if not m["nrt"] else NRT_GRACE)
                if bisect_right(at, due) - bisect_left(at, first["t"]) == 0:
                    kind = "monitoring_gap" if in_outage(first["t"], due) else "overdue_ack"
                    alerts.append((fid, occ, kind, due))
        for orig, e in dups:
            if id(orig) in occ_of:
                alerts.append((fid, occ_of[id(orig)], "duplicate_delivery", e["t"]))
    return alerts


def static_baseline(feeds, events, d0, d1, local=False):
    """Hand-configured rule per feed: fixed UTC time from onboarding (no DST, no calendar,
    send-only check, no ack linkage, no integrity checks)."""
    alerts = []
    by = defaultdict(list)
    for e in events:
        if e["kind"] == "send" and e["status"] == "ok":
            by[e["feed"]].append(e["t"])
    for f in feeds:
        ref = next(occurrences(f, TRAIN_START, TRAIN_END))
        off = ref.utcoffset()  # offset at onboarding, frozen
        tz = ZoneInfo(f["tz"])
        grace = NRT_GRACE if f["kind"] == "nrt" else BATCH_GRACE
        for d in daterange(d0, d1):
            if d.weekday() not in f["days"]:
                continue
            for h in (f["hours"] if f["kind"] == "nrt" else [f["hour"]]):
                exp = (datetime(d.year, d.month, d.day, h, f["minute"], tzinfo=tz).astimezone(UTC) if local
                       else datetime(d.year, d.month, d.day, h, f["minute"], tzinfo=UTC) - off)
                if not any(exp - timedelta(minutes=10) <= t <= exp + grace for t in by[f["id"]]):
                    alerts.append((f["id"], exp, "missing_delivery", exp + grace))
    return alerts


def main(seed=SEED):
    rng = random.Random(seed)
    feeds = make_feeds(rng)
    fmap = {f["id"]: f for f in feeds}
    train_ev, _ = gen_period(rng, feeds, TRAIN_START, TRAIN_END)
    t0 = time.perf_counter()
    mans = learn_manifests(feeds, train_ev, TRAIN_START, TRAIN_END)
    t_learn = time.perf_counter() - t0
    learned_ok = sum(1 for f in feeds if mans[f["id"]]["days"] == f["days"] and
                     (f["kind"] == "nrt" and mans[f["id"]]["hours"] == f["hours"] or
                      f["kind"] != "nrt" and mans[f["id"]]["hours"] == [f["hour"]]))

    # inject faults on test occurrences
    # pick a feed uniformly, then one of its occurrences, so batch feeds are not swamped by hourly ones
    per = {f["id"]: list(occurrences(f, TEST_START, TEST_END)) for f in feeds}
    occs = []
    for _ in range(5000):
        fid = rng.choice(feeds)["id"]
        occs.append((fid, rng.choice(per[fid])))
    occs = list(dict.fromkeys(occs))
    plan = {"missing_send": 40, "missing_ack": 30, "late_ack": 15, "duplicate": 15, "partial": 15, "retry": 20}
    faults, i = {}, 0
    for k, n in plan.items():
        c = 0
        while c < n:
            fid, o = occs[i]; i += 1
            if k in ("missing_ack", "late_ack") and not fmap[fid]["has_ack"]:
                continue
            faults[(fid, o.isoformat())] = k; c += 1
    # legitimate schedule change: 3 weekly feeds move one weekday later from 2026-05-04
    changed = [f for f in feeds if f["kind"] == "weekly" and max(f["days"]) < 4][:3]
    test_ev = []
    ev_a, truth = gen_period(rng, [f for f in feeds if f not in changed], TEST_START, TEST_END, faults)
    test_ev += ev_a
    for f in changed:
        e1, t1 = gen_period(rng, [f], TEST_START, date(2026, 5, 3), faults)
        g = dict(f, days={d + 1 for d in f["days"]})
        e2, t2 = gen_period(rng, [g], date(2026, 5, 4), TEST_END, faults)
        test_ev += e1 + e2; truth += t1 + t2
    # monitoring outage: collector down 2026-04-14 06:00-14:00 UTC, events in window lost
    outages = [(datetime(2026, 4, 14, 6, tzinfo=UTC), datetime(2026, 4, 14, 14, tzinfo=UTC))]
    lost = [e for e in test_ev if outages[0][0] <= e["t"] < outages[0][1]]
    test_ev = [e for e in test_ev if not (outages[0][0] <= e["t"] < outages[0][1])]

    t0 = time.perf_counter()
    alerts = reconcile(mans, test_ev, TEST_START, TEST_END, outages)
    t_rec = time.perf_counter() - t0
    base_local = static_baseline(feeds, test_ev, TEST_START, TEST_END, local=True)
    blf = Counter()
    realized_all = {(fid, o.isoformat()) for fid, o, flt in truth if flt}
    miss_l = {(fid, datetime.fromisoformat(o).astimezone(UTC).date()) for (fid, o), v in faults.items() if v == "missing_send" and (fid, o) in realized_all}
    bl_det = 0
    for fid, t, _, _ in base_local:
        if (fid, t.date()) in miss_l:
            bl_det += 1; continue
        d = t.date()
        if fmap[fid]["calendar"] and d in HOLIDAYS: blf["holiday"] += 1
        elif fmap[fid] in changed and d >= date(2026, 5, 4): blf["schedule change"] += 1
        elif outages[0][0] - timedelta(hours=6) <= t <= outages[0][1] + timedelta(hours=6): blf["collector outage"] += 1
        else: blf["other"] += 1
    base = static_baseline(feeds, test_ev, TEST_START, TEST_END)

    # score: map fault -> expected alert kind
    want = {"missing_send": "missing_delivery", "missing_ack": "overdue_ack", "late_ack": "overdue_ack",
            "duplicate": "duplicate_delivery", "partial": "partial_delivery"}
    K = lambda fid, occ: (fid, occ.date(), occ.hour if fmap[fid]["kind"] == "nrt" else 0)
    fk_of = {K(fid, datetime.fromisoformat(o)): v for (fid, o), v in faults.items()}
    akey = defaultdict(list)
    for fid, occ, kind, t in alerts:
        akey[K(fid, occ)].append((kind, t))
    res = {}
    for fk, k in want.items():
        realized = {(fid, o.isoformat()) for fid, o, flt in truth if flt}
        keys = [key for key, v in faults.items() if v == fk and key in realized]
        det = [key for key in keys if any(a[0] == k for a in akey[K(key[0], datetime.fromisoformat(key[1]))])]
        gapd = [key for key in keys if key not in det and any(a[0] == "monitoring_gap" for a in akey[K(key[0], datetime.fromisoformat(key[1]))])]
        res[fk] = (len(keys), len(det), len(gapd))
    injected_keys = set(faults)
    fp = Counter()
    gap = 0
    for fid, occ, kind, t in alerts:
        if kind == "monitoring_gap":
            gap += 1; continue
        fv = fk_of.get(K(fid, occ))
        if fv and want.get(fv) == kind:
            continue
        cause = "schedule change" if fmap[fid] in changed else kind
        fp[cause] += 1
    realized_all = {(fid, o.isoformat()) for fid, o, flt in truth if flt}
    retry_total = sum(1 for key, v in faults.items() if v == "retry" and key in realized_all)
    retry_alerts = sum(1 for key, v in faults.items() if v == "retry" and key in realized_all and akey[K(key[0], datetime.fromisoformat(key[1]))])
    # baseline scoring (send-only)
    bkeys = {(fid, t.date()) for fid, t, _, _ in base}
    b_missing = [key for key, v in faults.items() if v == "missing_send" and key in realized_all]
    b_det = sum(1 for fid, o in b_missing if (fid, datetime.fromisoformat(o).astimezone(UTC).date()) in bkeys)
    miss_true = {(fid, datetime.fromisoformat(o).astimezone(UTC).date()) for fid, o in b_missing}
    b_fp = Counter()
    for fid, t, _, _ in base:
        if (fid, t.date()) in miss_true:
            continue
        d = t.date()
        if fmap[fid]["calendar"] and any(abs((d - h).days) <= 1 for h in HOLIDAYS):
            b_fp["holiday"] += 1
        elif fmap[fid] in changed and d >= date(2026, 5, 4):
            b_fp["schedule change"] += 1
        elif outages[0][0] - timedelta(hours=6) <= t <= outages[0][1] + timedelta(hours=6):
            b_fp["collector outage"] += 1
        else:
            b_fp["DST offset shift"] += 1
    out = {
        "feeds": len(feeds), "feed_mix": Counter(f["kind"] for f in feeds), "acked_feeds": sum(f["has_ack"] for f in feeds),
        "train_events": len(train_ev), "test_events": len(test_ev), "lost_in_outage": len(lost),
        "expected_test_occurrences": len(truth), "manifests_learned_exactly": learned_ok,
        "learn_seconds": round(t_learn, 3), "reconcile_seconds": round(t_rec, 3),
        "detection": res, "retry_occurrences_alerted": retry_alerts, "retry_total": retry_total, "etm_false_alerts": fp,
        "etm_monitoring_gap_alerts": gap,
        "baseline_missing_detected": (len(b_missing), b_det), "baseline_false_alerts": b_fp,
        "baseline_total_alerts": len(base), "etm_total_alerts": len(alerts),
        "changed_feeds": [f["id"] for f in changed],
        "local_baseline_missing_detected": bl_det, "local_baseline_false_alerts": blf, "local_baseline_total": len(base_local),
        "faults_planned": plan, "holiday_occurrences_skipped": sum(1 for f in feeds if f["calendar"] for d in HOLIDAYS if TEST_START <= d <= TEST_END and d.weekday() in f["days"]),
    }
    return out


if __name__ == "__main__":
    runs = [main(s) for s in range(1, 6)]
    agg = {}
    for r in runs:
        for k, v in r.items():
            if k == "detection":
                for fk, (n, d, g) in v.items():
                    a = agg.setdefault("detection", {}).setdefault(fk, [0, 0, 0]); a[0] += n; a[1] += d; a[2] += g
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                agg[k] = agg.get(k, 0) + v
            elif isinstance(v, (Counter, dict)) and k != "faults_planned":
                c = agg.setdefault(k, Counter()); c.update(v)
            elif isinstance(v, tuple):
                a = agg.setdefault(k, [0, 0]); a[0] += v[0]; a[1] += v[1]
    agg["runs"] = len(runs)
    agg["max_reconcile_seconds"] = max(r["reconcile_seconds"] for r in runs)
    agg["per_run_manifests_exact"] = [r["manifests_learned_exactly"] for r in runs]
    print(json.dumps(agg, indent=1, default=dict))
