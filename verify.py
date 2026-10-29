"""Byte-for-byte regeneration check for the published benchmark and results."""
import json
import tempfile
from pathlib import Path
from simulate import generate
from evaluate import run


def verify():
    root=Path(__file__).resolve().parent
    expected=root/'benchmark/v1'
    meta=json.loads((expected/'metadata.json').read_text())
    with tempfile.TemporaryDirectory() as tmp:
        generated=Path(tmp)/'v1'
        generate(generated,meta['seed'],meta['repetitions'])
        for source in expected.iterdir():
            if source.is_file() and source.read_bytes()!=(generated/source.name).read_bytes():
                raise ValueError('Reproduction mismatch: '+source.name)
        report=json.dumps(run(generated),indent=2,sort_keys=True)+'\n'
        if report!=(root/'benchmark/results.json').read_text():
            raise ValueError('Reproduction mismatch: results.json')
    print('Dataset and evaluation reproduce byte for byte.')

if __name__=='__main__':
    verify()
