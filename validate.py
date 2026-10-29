"""Optional JSON Schema validation; install requirements-dev.txt first."""
import argparse
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from monitor import expand, evaluate, instant
from datetime import date


def validate(manifest_path, events_path):
    root=Path(__file__).resolve().parent
    validators={n:Draft202012Validator(json.loads((root/'spec'/f'{n}.schema.json').read_text()),
                                     format_checker=FormatChecker()) for n in ('manifest','event')}
    manifest=json.loads(Path(manifest_path).read_text())
    validators['manifest'].validate(manifest)
    events=[]
    for line in Path(events_path).read_text().splitlines():
        if line.strip():
            e=json.loads(line)
            validators['event'].validate(e)
            events.append(e)
    # Structural validation is complemented by duplicate and basic semantic checks.
    # Scheduling validation remains specific to the date range used by monitor.py.
    expand(manifest,date(2026,1,1),date(2026,1,31))
    evaluate([],events,instant('2026-01-01T00:00:00Z'))
    print('Schema and basic semantic validation passed (schedule dates require monitor evaluation).')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest');p.add_argument('events')
    a=p.parse_args();validate(a.manifest,a.events)
