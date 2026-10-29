import json
import unittest
from datetime import date
from monitor import expand, evaluate, instant

class MonitorTests(unittest.TestCase):
    def setUp(self):
        with open('examples/feeds.json') as f: self.config=json.load(f)
        with open('examples/events.jsonl') as f: self.events=[json.loads(x) for x in f]
        self.jobs=expand(self.config,date(2026,10,1),date(2026,10,31))
        self.now=instant('2026-10-15T01:00:00Z')
    def run_job(self, events): return evaluate(self.jobs,events,self.now)[0]
    def ack(self, **changes):
        return {'id':'ack-1','feed_id':'monthly-payroll','partner_id':'demo-partner','occurrence_id':'2026-10-12','kind':'business_ack','status':'success','timestamp':'2026-10-14T12:00:00-07:00','ack_ref':'batch-001',**changes}
    def test_second_monday(self): self.assertEqual(self.jobs[0]['due'],instant('2026-10-12T15:00:00Z'))
    def test_missing(self): self.assertEqual(self.run_job([])['findings'],['MISSING_FILE'])
    def test_transport_not_ack(self): self.assertEqual(self.run_job(self.events)['state'],'missing_ack')
    def test_correlated_complete(self): self.assertEqual(self.run_job(self.events+[self.ack()])['state'],'complete')
    def test_wrong_ref(self): self.assertEqual(self.run_job(self.events+[self.ack(ack_ref='wrong')])['state'],'missing_ack')
    def test_wrong_partner(self): self.assertEqual(self.run_job(self.events+[self.ack(partner_id='other')])['state'],'missing_ack')
    def test_wrong_occurrence(self): self.assertEqual(self.run_job(self.events+[self.ack(occurrence_id='2026-09-14')])['state'],'missing_ack')
    def test_future_ignored(self): self.assertEqual(self.run_job(self.events+[self.ack(timestamp='2026-10-16T01:00:00Z')])['state'],'missing_ack')
    def test_duplicate_idempotent(self): self.assertEqual(self.run_job(self.events*2),self.run_job(self.events))
    def test_conflicting_duplicate(self):
        with self.assertRaises(ValueError): self.run_job(self.events+[{**self.events[0],'status':'failed'}])
    def test_failed_transfer(self): self.assertEqual(self.run_job([{**self.events[0],'status':'failed'}])['state'],'missing_file')
    def test_late_recovery(self): self.assertEqual(self.run_job(self.events+[self.ack(timestamp='2026-10-15T00:30:00Z')])['findings'],['LATE_ACK'])
    def test_deadline_boundary(self):
        self.now=self.jobs[0]['deadline']; self.assertEqual(self.run_job([])['state'],'missing_file')
        self.events[0]['timestamp']=self.now.isoformat(); self.assertEqual(self.run_job(self.events)['findings'],[])
    def test_early_ack_rejected(self): self.assertEqual(self.run_job(self.events+[self.ack(timestamp='2026-10-11T01:00:00Z')])['state'],'missing_ack')
    def test_naive_time(self):
        with self.assertRaises(ValueError): instant('2026-10-12T08:00:00')
    def test_dst_offset(self):
        jobs=expand(self.config,date(2026,11,1),date(2026,11,30)); self.assertEqual(jobs[0]['due'].hour,16)
    def test_dst_nonexistent(self):
        self.config['feeds'][0]['schedule']={'kind':'nth_weekday','nth':2,'weekday':6,'time':'02:30'}
        with self.assertRaises(ValueError): expand(self.config,date(2026,3,1),date(2026,3,31))
    def test_retry(self):
        failed={**self.events[0],'id':'failed-1','status':'failed'}
        self.assertEqual(self.run_job([failed]+self.events+[self.ack()])['state'],'complete')

if __name__=='__main__': unittest.main()
