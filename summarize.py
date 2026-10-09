"""Summarize measured stages per mode; never mix mock and real runs."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
import statistics

parser = argparse.ArgumentParser()
parser.add_argument('logs', nargs='+', type=Path)
args = parser.parse_args()
groups = defaultdict(list)
for path in args.logs:
    for line in path.read_text().splitlines():
        row = json.loads(line)
        for field in ['from_start_ms', 'from_end_ms', 'from_commit_ms', 'request_ms', 'queue_ms']:
            if field in row:
                event = row['event'] + ('_preview' if row.get('provisional') else '')
                groups[(row['mode'], event, field)].append(row[field])
for (mode, event, field), values in sorted(groups.items()):
    ordered = sorted(values)
    p95 = ordered[max(0, __import__('math').ceil(.95 * len(ordered)) - 1)]
    print(f'{mode:12} {event:15} {field:17} n={len(values):3} '
          f'p50={statistics.median(values):8.0f} ms p95={p95:8.0f} ms')
