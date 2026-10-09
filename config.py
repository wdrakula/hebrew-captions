"""Settings exclude credentials; secrets are loaded without printing or copying."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEY_FILE = ROOT.parents[2] / 'APIkey.txt' if len(ROOT.parents) > 2 else None
SETTINGS = ROOT / 'settings.json'


def load_key():
    if os.environ.get('OPENAI_API_KEY'):
        return os.environ['OPENAI_API_KEY'].strip()
    env = ROOT / '.env'
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith('OPENAI_API_KEY='):
                return line.split('=',1)[1].strip().strip('\"\'')
    for path in (ROOT / 'APIkey.txt', KEY_FILE):
        if path is not None and path.exists():
            return path.read_text().strip()
    return ''


def load_settings():
    try:
        data = json.loads(SETTINGS.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data):
    temp = SETTINGS.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temp.replace(SETTINGS)
