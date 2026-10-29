"""Rerun the paper experiment and compare with the published results.json.

Timing fields depend on the machine and are not compared.
"""
import json
import subprocess
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
TIMING = ('learn_seconds', 'reconcile_seconds', 'max_reconcile_seconds')


def strip(d):
    return {k: v for k, v in d.items() if k not in TIMING}


def main():
    run = subprocess.run([sys.executable, str(here/'etm_sim.py')], capture_output=True, text=True, check=True)
    fresh = json.loads(run.stdout)
    published = json.loads((here/'results.json').read_text())
    if strip(fresh) != strip(published):
        for k in sorted(set(fresh) | set(published)):
            if k not in TIMING and fresh.get(k) != published.get(k):
                print(f'mismatch {k}: {fresh.get(k)} != {published.get(k)}')
        return 1
    print('Paper experiment reproduces results.json (timing fields excluded).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
