"""Evaluate fixed synthetic labels against ETM and two deliberately simple baselines."""
import argparse
import json
from datetime import date
from pathlib import Path
from monitor import evaluate, expand, instant

CLASSES=('MISSING_FILE','LATE_FILE','MISSING_ACK','LATE_ACK')

def key(row):
    return tuple(row[k] for k in ('feed_id','partner_id','occurrence_id'))

def score(truth, predictions):
    if set(truth) != set(predictions):
        raise ValueError('Prediction and label occurrence keys differ')
    counts={c:{'tp':0,'fp':0,'fn':0} for c in CLASSES}
    for k, labels in truth.items():
        for c in CLASSES:
            actual, predicted = c in labels, c in predictions[k]
            counts[c]['tp'] += int(actual and predicted)
            counts[c]['fp'] += int(not actual and predicted)
            counts[c]['fn'] += int(actual and not predicted)
    def metrics(v):
        tp,fp,fn=v['tp'],v['fp'],v['fn']
        return {**v,'precision':tp/(tp+fp) if tp+fp else None,
                'recall':tp/(tp+fn) if tp+fn else None,
                'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None}
    total={m:sum(v[m] for v in counts.values()) for m in ('tp','fp','fn')}
    return {'exact_match':sum(set(v)==set(predictions[k]) for k,v in truth.items())/len(truth),
            'micro':metrics(total),'per_class':{c:metrics(v) for c,v in counts.items()}}

def run(folder):
    folder=Path(folder)
    read=lambda n:json.loads((folder/n).read_text())
    meta,manifest,labels=read('metadata.json'),read('manifest.json'),read('labels.json')
    events=[json.loads(l) for l in (folder/'events.jsonl').read_text().splitlines() if l.strip()]
    jobs=expand(manifest,date.fromisoformat(meta['start']),date.fromisoformat(meta['end']))
    now=instant(meta['as_of'])
    truth={key(l):l['findings'] for l in labels}
    if len(truth)!=len(labels) or not truth:
        raise ValueError('Labels must be nonempty and unique')
    result=evaluate(jobs,events,now)
    methods={'etm':{key(r):r['findings'] for r in result}}
    # Ablation 1: same transfer rules, with no ACK checking.
    methods['transfer_only']={key(r):[f for f in r['findings'] if f.endswith('_FILE')] for r in result}
    # Ablation 2: treat any successful ACK/receipt within an occurrence as confirmation.
    # Deliberately ignores ack_ref and ACK-before-transfer ordering.
    naive={}
    for r in result:
        k=key(r)
        findings=[f for f in r['findings'] if f.endswith('_FILE')]
        if r['transfer_event_id']:
            acks=[instant(e['timestamp']) for e in events if key(e)==k and
                  e['kind'] in ('business_ack','transport_receipt') and e['status']=='success'
                  and instant(e['timestamp'])<=now]
            if not acks and now>=instant(r['ack_due']): findings.append('MISSING_ACK')
            elif acks and min(acks)>instant(r['ack_due']): findings.append('LATE_ACK')
        naive[k]=findings
    methods['uncorrelated_receipt']=naive
    return {'dataset_version':'1.0.0','occurrences':len(truth),'seed':meta['seed'],
            'interpretation':'Synthetic conformance evaluation; not field accuracy or evidence of novelty.',
            'methods':{name:score(truth,pred) for name,pred in methods.items()}}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',default='benchmark/v1')
    p.add_argument('--out',default='benchmark/results.json')
    a=p.parse_args()
    report=run(a.data)
    Path(a.out).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    for name,r in report['methods'].items():
        print(f"{name}: exact match={r['exact_match']:.3f}; micro F1={r['micro']['f1']:.3f}")
