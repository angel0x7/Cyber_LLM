import json
import os
import time
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parents[2] / 'reports' / 'application.jsonl'

def log(event):
    path = Path(os.getenv('LLM_LOG_PATH', str(LOG_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **event})+'\n')

def finish(trace, track, event, result):
    trace['event'] = event
    trace['track'] = track
    log({'track': track, 'phase': event, 'trace': trace, 'result': result})
    return result
