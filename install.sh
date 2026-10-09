#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python - <<'PY'
import hashlib, json
from pathlib import Path
manifest=json.loads(Path('models/manifest.json').read_text())
if hashlib.sha256(Path('models/silero_vad.onnx').read_bytes()).hexdigest()!=manifest['sha256']:
    raise SystemExit('Silero model checksum does not match')
print('Установка завершена. Добавьте APIkey.txt и запустите ./run.sh')
PY
