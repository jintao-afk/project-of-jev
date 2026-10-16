"""Extract existing real records into a small offline task demonstration."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if __name__ == '__main__':
    sources = {
        'baseline.csv': 'logs/evaluations/v031-baseline-v030-20261015-120656-396458.json',
        'current.csv': 'logs/evaluations/v031-contract-20261015-121826-442178.json',
    }
    folder = ROOT / 'workspace/inbox/demo'
    folder.mkdir(parents=True, exist_ok=True)
    for name, source in sources.items():
        data = json.loads((ROOT / source).read_text('utf-8'))
        with (folder / name).open('x', encoding='utf-8', newline='') as stream:
            fields = ['case', 'status', 'total_ms', 'invocation_attempts', 'successful_calls', 'remote_attempts']
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in data['results']:
                report = row['report']
                writer.writerow({'case': row['case'], **{key: report[key] for key in fields[1:]}})
        print(folder / name)
