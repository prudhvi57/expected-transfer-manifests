"""Deterministic, synthetic ETM benchmark generator; no monitor imports."""
import argparse
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = '1.0.0'
# Labels are prescribed by scenario design, never computed by the detector.
SCENARIOS = {
    'on_time': [], 'missing_file': ['MISSING_FILE'],
    'failed_only': ['MISSING_FILE'], 'late_file': ['LATE_FILE'],
    'missing_ack': ['MISSING_ACK'], 'late_ack': ['LATE_ACK'],
    'receipt_only': ['MISSING_ACK'], 'wrong_reference': ['MISSING_ACK'],
    'wrong_partner': ['MISSING_ACK'], 'ack_before_transfer': ['MISSING_ACK'],
    'retry_success': [], 'duplicate_events': [], 'deadline_exact': [],
    'late_both': ['LATE_FILE', 'LATE_ACK'],
}

def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')

def generate(out, seed=42, repetitions=30):
    if repetitions < 1:
        raise ValueError('repetitions must be positive')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    feeds, events, labels = [], [], []
    due = datetime(2026, 1, 5, 8, tzinfo=timezone.utc)
    deadline, ack_due = due+timedelta(hours=5), due+timedelta(days=2, hours=9)
    for scenario, truth in SCENARIOS.items():
        for n in range(repetitions):
            fid = f'{scenario}-{n:04d}'
            feeds.append({'id': fid, 'partner_id': 'synthetic-partner', 'timezone': 'UTC',
                          'schedule': {'kind':'weekly','weekday':0,'time':'08:00'},
                          'grace_minutes':300, 'ack': {'days_after':2,'time':'17:00'}})
            labels.append({'feed_id':fid,'partner_id':'synthetic-partner',
                           'occurrence_id':'2026-01-05','scenario':scenario,'findings':truth})
            transfer_time = due+timedelta(minutes=rng.randrange(0, 301))
            ack_time = ack_due-timedelta(minutes=rng.randrange(1, 600))
            if scenario in ('late_file','late_both'):
                transfer_time = deadline+timedelta(minutes=rng.randrange(1, 181))
            if scenario in ('late_ack','late_both'):
                ack_time = ack_due+timedelta(minutes=rng.randrange(1, 181))
            if scenario == 'deadline_exact':
                transfer_time, ack_time = deadline, ack_due
            batch = fid+'-transfer'
            def event(suffix, kind, stamp, **extra):
                return {'id':fid+'-'+suffix,'feed_id':fid,'partner_id':'synthetic-partner',
                        'occurrence_id':'2026-01-05','kind':kind,'status':'success',
                        'timestamp':stamp.isoformat(),**extra}
            if scenario == 'missing_file':
                continue
            tr = event('transfer', 'transfer', transfer_time, transfer_id=batch)
            if scenario == 'failed_only':
                tr['status']='failed'
                events.append(tr)
                continue
            if scenario == 'retry_success':
                events.append(event('failed', 'transfer', due-timedelta(minutes=1),
                                    transfer_id=batch+'-failed', status='failed'))
            events.append(tr)
            if scenario == 'missing_ack':
                continue
            ack = event('ack', 'business_ack', ack_time, ack_ref=batch)
            if scenario == 'receipt_only':
                ack['kind']='transport_receipt'
            if scenario == 'wrong_reference':
                ack['ack_ref']='unrelated-reference'
            if scenario == 'wrong_partner':
                ack['partner_id']='other-partner'
            if scenario == 'ack_before_transfer':
                ack['timestamp']=(transfer_time-timedelta(seconds=1)).isoformat()
            events.append(ack)
            if scenario == 'duplicate_events':
                events.extend([dict(tr),dict(ack)])
    rng.shuffle(events)
    dump(out/'manifest.json', {'spec_version':'1.0','feeds':feeds})
    (out/'events.jsonl').write_text(''.join(json.dumps(e, sort_keys=True)+'\n' for e in events))
    dump(out/'labels.json', labels)
    dump(out/'metadata.json', {'generator_version':VERSION,'seed':seed,'repetitions':repetitions,
         'occurrences':len(labels),'event_rows':len(events),'start':'2026-01-05','end':'2026-01-05',
         'as_of':'2026-01-08T00:00:00+00:00','synthetic':True})
    names=['manifest.json','events.jsonl','labels.json','metadata.json']
    (out/'SHA256SUMS').write_text(''.join(hashlib.sha256((out/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in names))

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',default='benchmark/v1')
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--repetitions',type=int,default=30)
    a=p.parse_args()
    generate(a.out,a.seed,a.repetitions)
