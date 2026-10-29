import json
import tempfile
import unittest
from pathlib import Path
from datetime import date
from simulate import generate, SCENARIOS
from evaluate import run, score
from monitor import evaluate, expand, instant

class BenchmarkTests(unittest.TestCase):
    def test_all_scenarios_and_baselines(self):
        with tempfile.TemporaryDirectory() as tmp:
            generate(tmp,seed=7,repetitions=2)
            report=run(tmp)
            self.assertEqual(report['occurrences'],len(SCENARIOS)*2)
            self.assertEqual(report['methods']['etm']['exact_match'],1)
            self.assertLess(report['methods']['transfer_only']['exact_match'],1)
            self.assertLess(report['methods']['uncorrelated_receipt']['exact_match'],1)

    def test_reproducibility_and_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b,c=[Path(tmp)/n for n in ('a','b','c')]
            generate(a,42,2);generate(b,42,2);generate(c,43,2)
            for f in a.iterdir(): self.assertEqual(f.read_bytes(),(b/f.name).read_bytes())
            self.assertNotEqual((a/'events.jsonl').read_bytes(),(c/'events.jsonl').read_bytes())

    def test_metric_known_errors(self):
        r=score({'a':['MISSING_FILE'],'b':[]},{'a':[],'b':['MISSING_ACK']})
        self.assertEqual(r['exact_match'],0)
        self.assertEqual(r['micro'],{'tp':0,'fp':1,'fn':1,'precision':0,'recall':0,'f1':0})
        with self.assertRaises(ValueError): score({'a':[]},{'b':[]})

    def test_future_ack_ignored_then_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            generate(tmp,42,1)
            p=Path(tmp)
            manifest=json.loads((p/'manifest.json').read_text())
            events=[json.loads(x) for x in (p/'events.jsonl').read_text().splitlines()]
            jobs=expand(manifest,date(2026,1,5),date(2026,1,5))
            rows=evaluate(jobs,events,instant('2026-01-07T17:00:00Z'))
            late=next(r for r in rows if r['feed_id']=='late_ack-0000')
            self.assertEqual(late['findings'],['MISSING_ACK'])
            rows=evaluate(jobs,events,instant('2026-01-08T00:00:00Z'))
            late=next(r for r in rows if r['feed_id']=='late_ack-0000')
            self.assertEqual(late['findings'],['LATE_ACK'])

    def test_wrong_occurrence_ack_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            generate(tmp,42,1)
            p=Path(tmp)
            manifest=json.loads((p/'manifest.json').read_text())
            manifest['feeds']=[f for f in manifest['feeds'] if f['id']=='on_time-0000']
            events=[json.loads(x) for x in (p/'events.jsonl').read_text().splitlines()]
            events=[e for e in events if e['feed_id']=='on_time-0000']
            for e in events:
                if e['kind']=='business_ack': e['occurrence_id']='2026-01-12'
            jobs=expand(manifest,date(2026,1,5),date(2026,1,5))
            self.assertEqual(evaluate(jobs,events,instant('2026-01-08T00:00:00Z'))[0]['findings'],['MISSING_ACK'])

    def test_invalid_generation_size(self):
        with self.assertRaises(ValueError): generate('unused',42,0)
