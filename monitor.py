"""Metadata-only scheduled feed and business ACK monitoring. Python 3.11+."""
import argparse
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def instant(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Timestamps must include a UTC offset')
    return dt.astimezone(timezone.utc)


def local_instant(day, clock, zone):
    naive = datetime.combine(day, time.fromisoformat(clock))
    if naive.tzinfo is not None:
        raise ValueError('Schedule time must be local, without offset')
    aware = naive.replace(tzinfo=zone)
    if aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != naive:
        raise ValueError('Schedule falls in a nonexistent DST time')
    if aware.utcoffset() != naive.replace(tzinfo=zone, fold=1).utcoffset():
        raise ValueError('Ambiguous DST time; choose an unambiguous schedule time')
    return aware.astimezone(timezone.utc)


def expand(config, start, end):
    """Expand inclusive date range; each feed supports weekly or nth weekday/month."""
    if end < start or (end-start).days > 3660:
        raise ValueError('Date range must be ordered and at most 3660 days')
    if config.get('spec_version') != '1.0':
        raise ValueError('spec_version must be 1.0')
    jobs, ids = [], set()
    for feed in config['feeds']:
        fid = feed['id']
        if not fid or fid in ids:
            raise ValueError('Feed IDs must be nonempty and unique')
        ids.add(fid)
        s = feed['schedule']
        if s['kind'] not in ('weekly', 'nth_weekday'):
            raise ValueError('Unsupported schedule kind')
        if type(s['weekday']) is not int or not 0 <= s['weekday'] <= 6:
            raise ValueError('weekday must be 0 (Monday) through 6')
        if s['kind'] == 'nth_weekday' and (type(s.get('nth')) is not int or s.get('nth') not in range(1, 6)):
            raise ValueError('nth must be 1 through 5')
        grace, ack_days = feed['grace_minutes'], feed['ack']['days_after']
        if type(grace) is not int or grace < 0 or type(ack_days) is not int or ack_days < 0:
            raise ValueError('Grace and ACK days must be nonnegative integers')
        zone = ZoneInfo(feed['timezone'])
        day = start
        while day <= end:
            if day.weekday() == s['weekday'] and (s['kind'] == 'weekly' or (day.day-1)//7+1 == s['nth']):
                due = local_instant(day, s['time'], zone)
                deadline = due + timedelta(minutes=grace)
                ack_due = local_instant(day+timedelta(days=ack_days), feed['ack']['time'], zone)
                if ack_due < deadline:
                    raise ValueError('ACK deadline must not precede transfer deadline')
                jobs.append({'feed_id': fid, 'partner_id': feed['partner_id'],
                             'occurrence_id': day.isoformat(), 'due': due,
                             'deadline': deadline, 'ack_due': ack_due})
            day += timedelta(days=1)
    return jobs


def evaluate(jobs, events, now):
    """Evaluate as-of event time; transport receipts never count as business ACKs."""
    if now.tzinfo is None:
        raise ValueError('now must be timezone aware')
    seen, valid = {}, []
    for event in events:
        for key in ('id', 'feed_id', 'partner_id', 'occurrence_id', 'kind', 'status', 'timestamp'):
            if not isinstance(event.get(key), str) or not event[key]:
                raise ValueError('Missing or invalid event field: '+key)
        stamp = instant(event['timestamp'])
        if event['id'] in seen:
            if event != seen[event['id']]:
                raise ValueError('Conflicting duplicate event ID: '+event['id'])
            continue
        seen[event['id']] = event
        if event['kind'] not in ('transfer', 'business_ack', 'transport_receipt'):
            raise ValueError('Unknown event kind')
        if event['status'] not in ('success', 'failed'):
            raise ValueError('Unknown event status')
        if event['kind'] == 'transfer' and (not isinstance(event.get('transfer_id'), str) or not event['transfer_id']):
            raise ValueError('Transfer requires transfer_id')
        if event['kind'] == 'business_ack' and (not isinstance(event.get('ack_ref'), str) or not event['ack_ref']):
            raise ValueError('Business ACK requires ack_ref')
        if stamp <= now:
            valid.append((stamp, event))
    output = []
    for job in jobs:
        matching = [(t,e) for t,e in valid if all(e[k] == job[k] for k in ('feed_id','partner_id','occurrence_id'))]
        transfers = sorted([(t,e) for t,e in matching if e['kind']=='transfer' and e['status']=='success'], key=lambda x:(x[0],x[1]['id']))
        acks = sorted([(t,e) for t,e in matching if e['kind']=='business_ack' and e['status']=='success'
                       and any(e['ack_ref']==tr['transfer_id'] and t>=tt for tt,tr in transfers)], key=lambda x:(x[0],x[1]['id']))
        first = transfers[0][0] if transfers else None
        ack = acks[0][0] if acks else None
        findings = []
        if first is None:
            if now >= job['deadline']:
                findings.append('MISSING_FILE')
            state = 'missing_file' if findings else 'waiting_file'
        else:
            if first > job['deadline']:
                findings.append('LATE_FILE')
            if ack is None:
                if now >= job['ack_due']:
                    findings.append('MISSING_ACK')
                state = 'missing_ack' if now >= job['ack_due'] else 'waiting_ack'
            else:
                if ack > job['ack_due']:
                    findings.append('LATE_ACK')
                state = 'complete_late' if findings else 'complete'
        output.append({**{k:v.isoformat() if isinstance(v,datetime) else v for k,v in job.items()},
                       'state':state, 'findings':findings,
                       'transfer_event_id':transfers[0][1]['id'] if transfers else None,
                       'ack_event_id':acks[0][1]['id'] if acks else None,
                       'explanation':f"Transfer required by {job['deadline'].isoformat()}; correlated business ACK by {job['ack_due'].isoformat()}"})
    return output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', required=True)
    p.add_argument('--events', required=True, help='JSONL metadata events')
    p.add_argument('--start', required=True, type=date.fromisoformat)
    p.add_argument('--end', required=True, type=date.fromisoformat)
    p.add_argument('--now', required=True, type=instant)
    args = p.parse_args()
    try:
        with open(args.config) as f:
            config = json.load(f)
        with open(args.events) as f:
            events = [json.loads(line) for line in f if line.strip()]
        result = evaluate(expand(config,args.start,args.end),events,args.now)
        print(json.dumps(result,indent=2))
        return 1 if any(r['findings'] for r in result) else 0
    except (ValueError, KeyError, TypeError, OSError) as e:
        print('Invalid input: '+str(e),file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
