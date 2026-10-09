import json
import os
from pathlib import Path
import threading
import time
import uuid
from datetime import datetime, timezone


class Journal:
    def __init__(self, mode, folder=None):
        folder = Path(folder or Path(__file__).parent / 'logs')
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / (datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6] + '.jsonl')
        self.file = self.path.open('w', encoding='utf-8')
        os.chmod(self.path, 0o600)
        self.lock = threading.Lock()
        self.mode = mode
        self.emit('session_start', sample_rate=24000)

    def emit(self, event, **fields):
        with self.lock:
            if self.file.closed:
                return
            row = dict(event=event, mode=self.mode, monotonic=time.monotonic(),
                       utc=datetime.now(timezone.utc).isoformat())
            row.update(fields)
            self.file.write(json.dumps(row, ensure_ascii=False)+'\n')
            self.file.flush()

    def close(self):
        with self.lock:
            self.file.close()
